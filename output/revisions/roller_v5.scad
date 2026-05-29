
        // Generation: 5 | Session: test-env-id
        wall_thickness = 2.58;
        bore_clearance = 1.0100000000000002;
        roller_radius = 14.93;
        
        module roller() {
            difference() {
                cylinder(h=100, r=roller_radius, $fn=60);
                translate([0,0,-5])
                    cylinder(h=110, r=bore_clearance + 2, $fn=40);
            }
        }
        roller();
        