import asyncio
from concurrent.futures import ThreadPoolExecutor
import subprocess
import threading
from typing import Any, Callable, List

from gstwebrtcapp.utils.base import LOGGER


async def restart_wrapper(
    coro: Callable[..., asyncio.Future],
    *args: Any,
    condition_cb: Callable[..., bool] = lambda: True,
    restart_cb: Callable[..., asyncio.Future] = lambda: asyncio.sleep(1),
    is_raise_exception: bool = False,
) -> None:
    """
    An async wrapper that restarts a coroutine if it fails or got cancelled. It does not handle the runtime backend errors if given.

    :param coro: Coroutine
    :param args: Arguments to pass to the coroutine
    :param condition_cb: A callback that controls the execution of the coroutine's loop. By default, it is always True
    :param restart_cb: A callback that is awaited when the coroutine is cancelled. By default, it is just a 1 second sleep
    :param is_raise_exception: If True, the coroutine will raise an exception and stop if it fails
    """
    while condition_cb():
        try:
            await coro(*args)
        except asyncio.CancelledError:
            await restart_cb()
            continue
        except Exception as e:
            LOGGER.error(f"ERROR: Coroutine {coro.__name__} has encountered an exception:\n {e}")
            if is_raise_exception:
                raise e
            await asyncio.sleep(1)  # FIXME: ignore the restart_cb if exception is raised?
            continue


async def executor_wrapper(
    coro: Callable[..., asyncio.Future],
    *args: Any,
    condition_cb: Callable[..., bool] = lambda: True,
    restart_cb: Callable[..., asyncio.Future] = lambda: asyncio.sleep(1),
    is_raise_exception: bool = False,
) -> None:
    """
    An async wrapper with restarting feature that offloads a coroutine managed by the current event loop in another thread.

    :param coro: Coroutine
    :param args: Arguments to pass to the coroutine
    :param condition_cb: A callback that controls the execution of the coroutine's loop. By default, it is always True
    :param restart_cb: A callback that is awaited when the coroutine is cancelled. By default, it is just a 1 second sleep
    :param is_raise_exception: If True, the coroutine will raise an exception and stop if it fails
    """
    loop = asyncio.get_running_loop()
    executor = ThreadPoolExecutor(max_workers=1)

    def _run_coroutine_threadsafe(loop, coro):
        return asyncio.run_coroutine_threadsafe(coro, loop).result()

    try:
        while condition_cb():
            try:
                await loop.run_in_executor(executor, _run_coroutine_threadsafe, loop, coro(*args))
            except asyncio.CancelledError:
                await restart_cb()
                continue
            except Exception as e:
                LOGGER.error(f"ERROR: Coroutine {coro.__name__} has encountered an exception:\n {e}")
                if is_raise_exception:
                    raise e
                await asyncio.sleep(1)
                continue
    finally:
        executor.shutdown(wait=False)


def threaded_wrapper(
    coro: Callable[..., asyncio.Future],
    *args: Any,
    is_daemon: bool = True,
    condition_cb: Callable[..., bool] = lambda: True,
    restart_cb: Callable[..., asyncio.Future] = lambda: asyncio.sleep(1),
    is_raise_exception: bool = False,
) -> asyncio.Future:
    """
    A sync wrapper with restarting feature that packs a coroutine in another thread and manages it using a new event loop.

    :param coro: Coroutine to monitor
    :param args: Arguments to pass to the coroutine
    :param is_daemon: If True, the thread will be a daemon thread
    :param condition_cb: A callback that controls the execution of the coroutine's loop. By default, it is always True
    :param restart_cb: A callback that is awaited when the coroutine is cancelled. By default, it is just a 1 second sleep
    :param is_raise_exception: If True, the coroutine will raise an exception and stop if it fails
    :return: A Future that completes when the threaded task is done
    """
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    result_queue = asyncio.Queue()

    def _run_coroutine_in_thread():
        try:
            import uvloop

            asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
        except ImportError:
            pass

        thread_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(thread_loop)

        async def __run_coro():
            while condition_cb():
                try:
                    await coro(*args)
                except asyncio.CancelledError:
                    await restart_cb()
                    continue
                except Exception as e:
                    LOGGER.error(f"ERROR: Coroutine {coro.__name__} has encountered an exception:\n {e}")
                    if is_raise_exception:
                        await result_queue.put(e)
                        return
                    await asyncio.sleep(1)
                    continue
            await result_queue.put(None)

        thread_loop.run_until_complete(__run_coro())
        thread_loop.close()

    thread = threading.Thread(target=_run_coroutine_in_thread, daemon=is_daemon)
    thread.start()

    def _cleanup_thread():
        if thread.is_alive():
            thread.join()

    def _check_result():
        async def check():
            try:
                result = result_queue.get_nowait()
                if result is not None:
                    if isinstance(result, Exception):
                        future.set_exception(result)
                    else:
                        future.set_result(None)
            except asyncio.QueueEmpty:
                loop.call_later(0.1, _check_result)

        asyncio.run_coroutine_threadsafe(check(), loop)

    loop.call_later(0.1, _check_result)
    future.add_done_callback(lambda _: _cleanup_thread())
    return future


def subprocess_wrapper(
    cmd: List[str],
    subprocess_name: str = "",
    condition_cb: Callable[..., bool] = lambda: True,
    restart_cb: Callable[..., None] = lambda: threading.Event().wait(1),
    is_raise_exception: bool = False,
) -> None:
    """
    A synchronous wrapper that restarts a subprocess if it fails or gets cancelled,
    capturing stdout and stderr. The cmd is supposed to be something like 'python coro.py <serialized_args>'.
    The separate coro.py file contains the logic of bulding and running the coroutine with the given serialized_args.

    :param cmd: The command to run in the subprocess (as a list of strings)
    :param condition_cb: A callback that controls the execution loop, default is always True
    :param restart_cb: A callback that is invoked when the subprocess is cancelled. Default is a 1 second wait
    :param is_raise_exception: If True, the wrapper will raise an exception and stop if subprocess fails
    """
    while condition_cb():
        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

            stdout, stderr = process.communicate()

            if process.returncode != 0:
                raise subprocess.CalledProcessError(process.returncode, cmd, output=stdout, stderr=stderr)

            if stdout:
                LOGGER.info(f"Subprocess {subprocess_name}: {stdout}")
            if stderr:
                LOGGER.error(f"Subprocess {subprocess_name}: {stderr}")

        except subprocess.CalledProcessError as e:
            LOGGER.error(
                f"Subprocess with command {cmd} failed with return code {e.returncode}:\n"
                f"stdout: {e.output}\nstderr: {e.stderr}"
            )
            if is_raise_exception:
                raise e
            restart_cb()
        except Exception as e:
            LOGGER.error(f"Unexpected error in subprocess with command {cmd}:\n {e}")
            if is_raise_exception:
                raise e
            restart_cb()
