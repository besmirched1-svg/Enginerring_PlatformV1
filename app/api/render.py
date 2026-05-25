from fastapi import APIRouter
from app.cad.openscad_service import OpenSCADService

router = APIRouter()


@router.post("/render")
def render_cube():

    output = OpenSCADService.render_scad_to_stl(
        "cube([20,20,20]);",
        "cube.stl"
    )

    return {
        "status": "success",
        "output": str(output)
    }