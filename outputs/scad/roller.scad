$fn = 180;

module roller(diameter=180, width=450, shaft=40) {
    difference() {
        cylinder(d=diameter, h=width);
        translate([0, 0, -1])
            cylinder(d=shaft, h=width + 2);
    }
}

roller();