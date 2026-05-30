
        wall_thickness = 3.07;
        bore_clearance = 1.07;
        roller_radius = 12.2;

        module roller() {
            difference() {
                cylinder(h=100, r=roller_radius, $fn=60);
                translate([0,0,-5])
                    cylinder(h=110, r=bore_clearance + 2, $fn=40);
            }
        }
        roller();
        