
        wall_thickness = 2.73;
        bore_clearance = 0.726;
        roller_radius = 15.85;

        module roller() {
            difference() {
                cylinder(h=100, r=roller_radius, $fn=60);
                translate([0,0,-5])
                    cylinder(h=110, r=bore_clearance + 2, $fn=40);
            }
        }
        roller();
        