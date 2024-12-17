# Docker installation
To overcome the installation and dependency hell, please deploy the Docker environment. You can use the Dockerfile-cpu (cpu version) or Dockerfile-cuda (cuda version with nv* plugins for hardware acceleration) to build the image. Check the possible software versions as build arguments [below](#versions-aka-build-arguments). You have two options of how to build and run.

## Compose
Install `docker-compose-plugin` plugin (>=v2) if not installed. Then go to the `docker` folder use cuda/cpu profiles to build and run the image with docker compose. `<?build_args>` denote optional build arguments that could be omitted or set via a compose file. E.g., for CUDA:
```bash
docker compose --profile cuda build <?build_args>
```
and for cpu:
```bash
docker compose --profile cpu build <?build_args>
```
Then run the container with:
```bash
docker compose --profile cuda up -d
```

or for the cpu version:
```bash
docker compose --profile cpu up -d
```

Then you can attach a shell to the container with:
```bash
docker exec -it <container_name> bash
```

## Manual
Go to the `docker` folder and build the CUDA image with:
```bash
docker build -f Dockerfile-cuda -t nsmirnov/gstwebrtcapp-cuda:latest <?build_args> .
```
To build the image without CUDA support, use:
```bash
docker build -f Dockerfile-cpu -t nsmirnov/gstwebrtcapp-cpu:latest <?build_args> .
```
Then run the container with:
```bash
docker run -d --name gstwebrtcapp-container --network=bridge -P --privileged --cap-add=NET_ADMIN <?display_args> nsmirnov/gstwebrtcap-cpu:latest bash
```
to run the CUDA container, use:
```bash 
docker run --gpus all -d --name gstwebrtcapp-container --network=bridge -P --privileged --cap-add=NET_ADMIN <?display_args> nsmirnov/gstwebrtcapp-cuda:latest bash
```	
where `<?display_args>` are the optional display options that could be skipped. On Linux:
```bash
-e DISPLAY=$YOUR_IPV4_ADDRESS:0 -v /tmp/.X11-unix:/tmp/.X11-unix
```
on Windows:
```bash
-e DISPLAY=host.docker.internal:0.0
```

# Versions aka build arguments
The Dockerfile-cuda allows to set the following arguments for the versions of the software:
* `CUDA_VER` - the version of the CUDA, e.g., 12.1
* `CUDA_VER_MINOR` - the minor version of the CUDA, e.g., 1
* `CUDNN_VER` - the version of the cuDNN, for cuda > 12.1 it is "cudnn", for older versions it is "cudnn<N>" where N is the version of the cuDNN, e.g., 8

The other are common for both Dockerfiles:
* `UBUNTU_VER` - the version of the Ubuntu, e.g., 22.04
* `GST_VER` - the version of the GStreamer git branch/tag, e.g., 1.24.10, or "main"
* `PYTHON_VER` - the version of the Python, e.g., 3.12.7

With the compose one can set them either in the compose file (build:args) or manually as the build arguments:
```bash
docker compose --profile cuda build --build-arg CUDA_VER=12.1 --build-arg CUDA_VER_MINOR=1 --build-arg CUDNN_VER=cudnn8 --build-arg UBUNTU_VER=22.04 --build-arg GST_VER=main --build-arg PYTHON_VER=3.12.7
```

same goes for the manual build:
```bash
docker build -f Dockerfile-cuda -t nsmirnov/gstwebrtcapp-cuda:latest --build-arg CUDA_VER=12.1 --build-arg CUDA_VER_MINOR=1 --build-arg CUDNN_VER=cudnn8 --build-arg UBUNTU_VER=22.04 --build-arg GST_VER=main --build-arg PYTHON_VER=3.12.7 .
```

same goes for the cpu version omitting the `CUDA_VER`, `CUDA_VER_MINOR` and `CUDNN_VER` arguments.

# Activate a wss listener for MQTT broker
1. Uncomment the `websocket` section in the `etc/mosquitto/mosquitto.conf` file.
2. Generate the self-signed certificate with the following commands (run one by one):
```bash
mkdir -p /etc/mosquitto/ssl 
cd /etc/mosquitto/ssl
openssl genrsa -des3 -out ca.key 2048 
openssl req -new -key ca.key -out ca-cert-request.csr -sha256
openssl x509 -req -in ca-cert-request.csr -signkey ca.key -out ca-root-cert.crt -days 365 -sha256
openssl genrsa -out server.key 2048
openssl req -new -key server.key -out server-cert-request.csr -sha256
openssl x509 -req -in server-cert-request.csr -CA ca-root-cert.crt -CAkey ca.key -CAcreateserial -out server.crt -days 360
chown mosquitto:mosquitto /etc/mosquitto/ssl/server.key
chmod 600 /etc/mosquitto/ssl/server.key
```
3. Restart the MQTT broker.

