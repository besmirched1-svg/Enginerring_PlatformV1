$fn = 180;

module roller(diameter=240, width=700, shaft=50) {
    difference() {
        cylinder(d=diameter, h=width);
        translate([0, 0, -1])
            cylinder(d=shaft, h=width + 2);
    }
}

roller();