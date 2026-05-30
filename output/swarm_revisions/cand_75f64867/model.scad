
        wall_thickness = 6.67;
        bore_clearance = 2.237;
        roller_radius = 46.88;

        module roller() {
            difference() {
                cylinder(h=100, r=roller_radius, $fn=60);
                translate([0,0,-5])
                    cylinder(h=110, r=bore_clearance + 2, $fn=40);
            }
        }
        roller();
        