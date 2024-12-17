def get_agent_type_by_switch_code(algo: int) -> str:
    match algo:
        case 0:
            return "gcc"
        case 1:
            return "drl"
        case 2:
            return "sd"
        case -1:
            return "man"
        case _:
            return "udf"


def get_switch_code_by_agent_type(agent_type: str) -> int:
    match agent_type:
        case "gcc":
            return 0
        case "drl":
            return 1
        case "sd":
            return 2
        case "man":
            return -1
        case _:
            return -2
