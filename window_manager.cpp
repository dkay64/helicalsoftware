#include "window_manager.h"
#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>
#include <sstream>
#include <fstream>

void moveWindowsToRightMonitor() {
    // Use wmctrl to get all windows and store in a file
    std::string command = "wmctrl -lG > window_list.txt";
    system(command.c_str());

    std::ifstream file("window_list.txt");
    std::string line;
    std::vector<std::string> windows;

    // Process each window's geometry and determine if it's on the left monitor
    while (std::getline(file, line)) {
        std::istringstream iss(line);
        std::string win_id;
        int x, y, width, height;
        iss >> win_id;  // Window ID
        iss >> std::skipws >> width >> height >> x >> y;  // Geometry

        // If the window is on the left monitor (Monitor 2: DP-0, 2560x1600)
        if (x >= 0 && x < 2560) {
            windows.push_back(win_id);
        }
    }
    file.close();

    // Move each window to the right monitor (Monitor 1: HDMI-0, 1920x1080, starting at 2560)
    for (const auto& win : windows) {
        std::string move_command = "wmctrl -ir " + win + " -e 0,2560,0,-1,-1";  // Move to (2560, 0)
        system(move_command.c_str());
    }

    // Clean up the temporary file
    system("rm window_list.txt");

    std::cout << "All windows from the left monitor (DP-0) have been moved to the right monitor (HDMI-0)." << std::endl;
}
