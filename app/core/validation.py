# app/core/validation.py

SAFE_LIMITS = {
    "diameter": (120, 600),
    "width": (100, 2000),
    "shaft": (20, 120),
    "wall_thickness": (4, 80),
}


def constrain(value, minimum, maximum):
    return max(minimum, min(value, maximum))


def constrain_config(config):

    constrained = dict(config)

    for key, limits in SAFE_LIMITS.items():

        if key in constrained:

            constrained[key] = constrain(
                constrained[key],
                limits[0],
                limits[1]
            )

    return constrained


def validate_machine_config(config):

    errors = []

    diameter = config.get("diameter", 0)
    shaft = config.get("shaft", 0)
    wall = config.get("wall_thickness", 8)
    width = config.get("width", 0)

    if shaft >= diameter:
        errors.append("shaft exceeds diameter")

    if wall * 2 >= diameter:
        errors.append("wall thickness invalid")

    if width <= 0:
        errors.append("width invalid")

    return {
        "valid": len(errors) == 0,
        "errors": errors
    }