$fn = 180;

module roller(diameter=450, width=700, shaft=40) {
    difference() {
        cylinder(d=diameter, h=width);
        translate([0, 0, -1])
            cylinder(d=shaft, h=width + 2);
    }
}

roller();