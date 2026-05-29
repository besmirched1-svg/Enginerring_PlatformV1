
        // Generation: 3 | Session: test-env-id
        wall_thickness = 2.5999999999999996;
        bore_clearance = 0.9400000000000002;
        roller_radius = 15.0;
        
        module roller() {
            difference() {
                cylinder(h=100, r=roller_radius, $fn=60);
                translate([0,0,-5])
                    cylinder(h=110, r=bore_clearance + 2, $fn=40);
            }
        }
        roller();
        