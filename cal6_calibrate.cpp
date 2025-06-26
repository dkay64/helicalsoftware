// cal6_calibrate.cpp

#include "Esp32UART.h"
#include "TicController.h"
#include "HeliCalHelper.h"    // for zeroAxisPair()
#include "LED.h"
#include "DLPC900.h"
#include <iostream>
#include <vector>
#include <string>
#include <sstream>
#include <unistd.h>  // usleep
#include <cctype>    // toupper

using namespace std;

// Compile in one line:
// g++ -std=c++17 -Wall -Wextra -pthread cal6_calibrate.cpp Esp32UART.cpp TicController.cpp HeliCalHelper.cpp LED.cpp DLPC900.cpp window_manager.cpp -I/usr/include/hidapi -lhidapi-hidraw -o cal6_calibrate

int main() {
    // --- 1) Instantiate controllers (exact lines restored) ---
    TicController tic_tw_z1("/dev/i2c-1", 0x10, 7, 2560000,2560000,450000000,2000);
    TicController tic_tw_z2("/dev/i2c-1", 0x11, 7, 2560000,2560000,450000000,2000);
    TicController tic_tw_t ("/dev/i2c-1", 0x0F, 4, 320000,320000,450000000,2000);
    TicController tic_tw_r ("/dev/i2c-1", 0x0E, 4, 320000,320000,450000000,2000);
    TicController tic_cw_z1("/dev/i2c-1", 0x14, 7, 2560000,2560000,450000000,2000);
    TicController tic_cw_z2("/dev/i2c-1", 0x15, 7, 2560000,2560000,450000000,2000);
    TicController tic_cw_t ("/dev/i2c-1", 0x13, 4, 320000,320000,450000000,2000);
    TicController tic_cw_r ("/dev/i2c-1", 0x12, 4, 320000,320000,450000000,2000);

    vector<TicController*> all = {
        &tic_tw_z1, &tic_tw_z2,
        &tic_tw_t,  &tic_tw_r,
        &tic_cw_z1, &tic_cw_z2,
        &tic_cw_t,  &tic_cw_r
    };

    // bring out of safe-start & energize
    for (auto m : all) {
        m->exitSafeStart();
        m->energize();
        m->setTargetVelocity(0);
    }

    // --- 2) Zero all axes ---
    cout << "Zeroing axes..." << endl;
    //zeroAxisPair(tic_tw_r, tic_cw_r, 1, -283000);                       // R
    //zeroAxisPair(tic_tw_t, tic_cw_t, 1, -335288);                       // T
    zeroAxisPair(tic_tw_z1, tic_tw_z2, tic_cw_z1, tic_cw_z2, 0, 24025); // Z
    cout << "All axes zeroed." << endl;

    // --- 3) Configure projector + LED ---
    LED     led;
    DLPC900 dlp;
    cout << "Configuring LED & DLP projector..." << endl;
    led.configure();
    led.current(450);
    if (!led.status()) cerr << "Warning: LED status failed\n";
    if (!led.temp())   cerr << "Warning: LED temp failed\n";
    dlp.configure();
    cout << "Projector ready." << endl;

    // --- 4) Interactive command loop ---
    //     Type Z9000, R-147000, etc.; a single space (" ") + ENTER aborts.
    string line;
    while (true) {
        cout << "> " << flush;
        if (!getline(cin, line)) break;  // EOF/Ctrl-D

        // 1) raw-space abort check
        if (line == " ") {
            cout << "Emergency STOP received." << endl;
            break;
        }

        // 2) trim whitespace
        auto i0 = line.find_first_not_of(" \t\r\n");
        if (i0 == string::npos) continue;
        auto i1 = line.find_last_not_of(" \t\r\n");
        string cmd = line.substr(i0, i1 - i0 + 1);

        // 3) validate length
        if (cmd.size() < 2) {
            cerr << "Invalid. Use R<pos>, T<pos>, Z<pos> (e.g. Z9000)" << endl;
            continue;
        }

        // 4) parse axis and position
        char axis = toupper(cmd[0]);
        string num = cmd.substr(1);
        if (axis!='R' && axis!='T' && axis!='Z') {
            cerr << "Unknown axis '"<< axis << "'. Use R, T or Z." << endl;
            continue;
        }
        int32_t pos;
        try {
            size_t idx;
            pos = stoi(num, &idx);
            if (idx != num.size()) throw invalid_argument("extra");
        } catch(...) {
            cerr << "Invalid numeric value: '"<< num << "'" << endl;
            continue;
        }

        // 5) dispatch
        switch(axis) {
            case 'R':
                tic_tw_r.setTargetPosition(pos);
                tic_cw_r.setTargetPosition(pos);
                cout << "R axes -> " << pos << endl;
                break;
            case 'T':
                tic_tw_t.setTargetPosition(pos);
                tic_cw_t.setTargetPosition(pos);
                cout << "T axes -> " << pos << endl;
                break;
            case 'Z':
                tic_tw_z1.setTargetPosition(pos);
                tic_tw_z2.setTargetPosition(pos);
                tic_cw_z1.setTargetPosition(pos);
                tic_cw_z2.setTargetPosition(pos);
                cout << "Z axes -> " << pos << endl;
                break;
        }
    }

    // --- 5) Cleanup ---
    cout << "Shutting off projector and de-energizing motors..." << endl;
    dlp.setVideoSource(DLPC900_IT6535MODE_POWERDOWN);
    led.stop();
    for (auto m : all) {
        m->deenergize();
    }
    cout << "Clean exit." << endl;
    return 0;
}
