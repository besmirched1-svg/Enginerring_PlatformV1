
        wall_thickness = 2.76;
        bore_clearance = 1.064;
        roller_radius = 14.96;

        module roller() {
            difference() {
                cylinder(h=100, r=roller_radius, $fn=60);
                translate([0,0,-5])
                    cylinder(h=110, r=bore_clearance + 2, $fn=40);
            }
        }
        roller();
        