#include "Esp32UART.h"
#include "TicController.h"
#include "HeliCalHelper.h"    // now has init_key_listener(), wait_or_abort(), abort_requested(), consume_enter(), restore_terminal()
#include "LED.h"
#include "DLPC900.h"
#include "window_manager.h"   // for sleepms()
#include <iostream>
#include <vector>
#include <exception>
#include <unistd.h>
#include <cstdlib>
#include <limits>
#include <chrono>
#include <thread>

using namespace std;

// g++ -std=c++17 -Wall -Wextra -pthread cal6_print_z_translation_multi_pass.cpp Esp32UART.cpp TicController.cpp HeliCalHelper.cpp LED.cpp DLPC900.cpp window_manager.cpp -I/usr/include/hidapi -lhidapi-hidraw -o cal6_print_z_translation_multi_pass


int main() {
    // Instantiate controllers
    TicController tic_tw_z1("/dev/i2c-1", 0x10, 7, 2560000,2560000,105000000,2000);
    TicController tic_tw_z2("/dev/i2c-1", 0x11, 7, 2560000,2560000,105000000,2000);
    TicController tic_tw_t ("/dev/i2c-1", 0x0F, 4, 320000,320000,450000000,2000);
    TicController tic_tw_r ("/dev/i2c-1", 0x0E, 4, 320000,320000,450000000,2000);
    TicController tic_cw_z1("/dev/i2c-1", 0x14, 7, 2560000,2560000,105000000,2000);
    TicController tic_cw_z2("/dev/i2c-1", 0x15, 7, 2560000,2560000,105000000,2000);
    TicController tic_cw_t ("/dev/i2c-1", 0x13, 4, 320000,320000,450000000,2000);
    TicController tic_cw_r ("/dev/i2c-1", 0x12, 4, 320000,320000,450000000,2000);

    vector<TicController*> all = {
        &tic_tw_z1, &tic_tw_z2, &tic_tw_t, &tic_tw_r,
        &tic_cw_z1, &tic_cw_z2, &tic_cw_t, &tic_cw_r
    };

    // exit safe-start & zero velocity
    for (auto m : all) {
        m->exitSafeStart();
        m->energize();
        m->setTargetVelocity(0);
    }

    // Interfaces
    LED      led;
    DLPC900  dlp;
    Esp32UART uart("/dev/ttyTHS1", 115200);

    // start keyboard listener & ensure cleanup on exit
    init_key_listener();

    try {
        // 1) Set DC PWM = 0
        cout << "DC PWM set to 0.\n";
        uart.setDcDriverPwm(0);

        // 2) Wait ENTER to home
        cout << "Press [ENTER] to begin homing all axes...\n";
        while (!consume_enter()) {
            if (abort_requested()) throw runtime_error("EMERGENCY STOP");
            this_thread::sleep_for(10ms);
        }

        // zero all axes (r, t, z-pair)
        //zeroAxisPair(tic_tw_r, tic_cw_r, 1, -283000);
        //zeroAxisPair(tic_tw_t, tic_cw_t, 1, -335287);
        zeroAxisPair(tic_tw_z1, tic_tw_z2, tic_cw_z1, tic_cw_z2, 0, 35000); //was 19000
        cout << "All axes zeroed.\n";

        // 3) Wait ENTER to spin theta or SPACE to abort
        cout << "Press [SPACE] to EMERGENCY STOP, or [ENTER] to enable rotational velocity\n";
        while (true) {
            if (abort_requested()) throw runtime_error("EMERGENCY STOP");
            if (consume_enter()) break;
            this_thread::sleep_for(10ms);
        }


        int32_t vel9rpm = static_cast<int32_t>(245426 * 9.0 / 60.0);
        uart.setThetaVelocity(vel9rpm);
        cout << "Theta velocity set to " << vel9rpm << " pulses/sec.\n";

        // 4) Wait ENTER to start video or SPACE to abort
        cout << "Press [SPACE] to EMERGENCY STOP, or [ENTER] to start video playback\n";
        while (true) {
            if (abort_requested()) throw runtime_error("EMERGENCY STOP");
            if (consume_enter()) break;
            this_thread::sleep_for(10ms);
        }

        // configure LED & DLP
        led.configure();
        led.PWM(0);
        dlp.configure();
        cout << "Waiting 1s before playing video...\n";
        sleep(1);
        system(
            "mpv --title=ProjectorVideo "
            "--pause "
            "--no-border --loop=inf "
            "--video-rotate=180 "
            "/home/jacob/Desktop/HeliCAL_Final/Videos/campanile_intensity7x_5cpp_updown_cropheight600px.mp4 &"
        );
        sleep(2);
        system("xdotool search --name ProjectorVideo windowmove 1920 0");
        system("xdotool search --name ProjectorVideo windowsize 2560 1600");
        system("xdotool search --name ProjectorVideo windowactivate --sync key f");

        cout << "Press [SPACE] to EMERGENCY STOP, or [ENTER] to play video\n";
        while (true) {
            if (abort_requested()) throw runtime_error("EMERGENCY STOP");
            if (consume_enter()) break;
            this_thread::sleep_for(10ms);
        }

        // turn on LED
        led.current(2500);
        led.PWM(255);

        // 5) Multi-pass Z translation
        const vector<int32_t> steps = {10432371, -10432371};
        const int start_delay_ms = 0;
        const int delay_ms = 33359;
        auto last_switch = chrono::steady_clock::now();
        auto next_switch = last_switch;
        bool did_unpause = false;

        cout << "Starting Z-axis multi-pass sequence\n";
        while (true) {
            for (auto v : steps) {
                
                if (!did_unpause) {
						system("xdotool search --name ProjectorVideo windowactivate --sync key space");
						this_thread::sleep_for(std::chrono::milliseconds(start_delay_ms));
						did_unpause = true;
					}
                
                // apply velocity
                tic_cw_z1.setTargetVelocity(v);
                tic_cw_z2.setTargetVelocity(v);
                tic_tw_z1.setTargetVelocity(v);
                tic_tw_z2.setTargetVelocity(v);
                
                next_switch += chrono::milliseconds(delay_ms);

                // print interval
                {
                    auto now = chrono::steady_clock::now();
                    auto delta = chrono::duration_cast<chrono::milliseconds>(now - last_switch).count();
                    cout << "Interval since last change: " << delta << " ms\n";
                    
					
					last_switch = now;
                    
                }

                // wait until next_switch, polling abort
                for (;;) {
                    if (abort_requested()) throw runtime_error("EMERGENCY STOP");
                    if (chrono::steady_clock::now() >= next_switch) break;
                    this_thread::sleep_for(1ms);
                }
            }
        }
    }
    catch (const exception &ex) {
        cerr << ">>> " << ex.what() << " exiting\n";
        // cleanup
        uart.setThetaVelocity(0);
        system("pkill mpv");
        dlp.setVideoSource(DLPC900_IT6535MODE_POWERDOWN);
        led.stop();
        for (auto m : all) m->deenergize();
        restore_terminal();
        return 1;
    }
    restore_terminal();
    return 0;
}
