
        wall_thickness = 2.78;
        bore_clearance = 1.037;
        roller_radius = 12.63;

        module roller() {
            difference() {
                cylinder(h=100, r=roller_radius, $fn=60);
                translate([0,0,-5])
                    cylinder(h=110, r=bore_clearance + 2, $fn=40);
            }
        }
        roller();
        