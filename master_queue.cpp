#include "Esp32UART.h"
#include "TicController.h"
#include "HeliCalHelper.h"    // zeroAxisPair(), init_key_listener(), abort_requested(), consume_enter(), restore_terminal()
#include "LED.h"
#include "DLPC900.h"

#include <iostream>
#include <vector>
#include <string>
#include <sstream>
#include <unordered_map>
#include <cctype>
#include <algorithm>
#include <chrono>
#include <thread>
#include <cmath>
#include <cstdlib>
#include <unistd.h>
#include <queue>
#include <iomanip>

// Sample commmand - for some reason z comm waits for us to press enter to be executed
/* G91 
 G0 R10000
 G0 T10000
 G1 T-10000 F50000000
 G0 R20000
 G1 Z-15000 F50000000
*/

using namespace std;

// ====== Tunables / constants ======
static constexpr int32_t COUNTS_PER_THETA_REV = 245426;   // pulses per revolution (theta encoder)
static inline int32_t rpm_to_pps(double rpm) {
    return static_cast<int32_t>((rpm * COUNTS_PER_THETA_REV) / 60.0);
}

// Rotation limits (A)
static constexpr double A_RPM_MIN = 0.0;
static constexpr double A_RPM_MAX = 60.0;     // A must be in [0,60] RPM

// Default homing: reuse your prior values
static constexpr uint8_t HOME_DIR_R = 1;       // in/out
static constexpr int32_t HOME_OFF_R = -283000;
static constexpr uint8_t HOME_DIR_T = 1;       // left/right
static constexpr int32_t HOME_OFF_T = -335288;
static constexpr uint8_t HOME_DIR_Z = 0;       // up/down
static constexpr int32_t HOME_OFF_Z = 24025;

// ====== Axis config you provided ======
static const uint32_t STEPPER_Z_STEPMODE        = 7;
static const uint32_t STEPPER_Z_MAXACCELERATION = 2560000;
static const uint32_t STEPPER_Z_MAXDECELERATION = 2560000;
static const uint32_t STEPPER_Z_MAXVELOCITY     = 105000000;  // speed cap for Z
static const uint32_t STEPPER_Z_MAXCURRENTmA    = 2000;

static const uint32_t STEPPER_RT_STEPMODE        = 4;
static const uint32_t STEPPER_RT_MAXACCELERATION = 320000;
static const uint32_t STEPPER_RT_MAXDECELERATION = 320000;
static const uint32_t STEPPER_RT_MAXVELOCITY     = 450000000;  // speed cap for R & T
static const uint32_t STEPPER_RT_MAXCURRENTmA    = 2000;

// ====== Helpers ======
struct AxisGroup {
    TicController* a = nullptr;
    TicController* b = nullptr;
    TicController* c = nullptr;
    TicController* d = nullptr;

    void setTargetPosition(int32_t pos) const {
        if (a) a->setTargetPosition(pos);
        if (b) b->setTargetPosition(pos);
        if (c) c->setTargetPosition(pos);
        if (d) d->setTargetPosition(pos);
    }
    void setMaxSpeed(uint32_t spd) const {
        if (a) a->setMaxSpeed(spd);
        if (b) b->setMaxSpeed(spd);
        if (c) c->setMaxSpeed(spd);
        if (d) d->setMaxSpeed(spd);
    }
    void energize() const {
        if (a) a->energize();
        if (b) b->energize();
        if (c) c->energize();
        if (d) d->energize();
    }
    void deenergize() const {
        if (a) a->deenergize();
        if (b) b->deenergize();
        if (c) c->deenergize();
        if (d) d->deenergize();
    }
    void exitSafeStart() const {
        if (a) a->exitSafeStart();
        if (b) b->exitSafeStart();
        if (c) c->exitSafeStart();
        if (d) d->exitSafeStart();
    }
    void haltAndHold() const {
		if (a) a->haltAndHold();
		if (b) b->haltAndHold();
		if (c) c->haltAndHold();
		if (d) d->haltAndHold();
	}
};

// Trim + strip comment after ';'
static inline string strip_comment_and_trim(const string& line) {
    auto semi = line.find(';');
    string s = (semi == string::npos) ? line : line.substr(0, semi);
    auto b = s.find_first_not_of(" \t\r\n");
    if (b == string::npos) return {};
    auto e = s.find_last_not_of(" \t\r\n");
    return s.substr(b, e - b + 1);
}

static bool parse_param(const std::string& token, char& key, double& value) {
    if (token.empty()) return false;
    key = static_cast<char>(std::toupper(static_cast<unsigned char>(token[0])));
    if (token.size() == 1) return false;
    try {
        value = std::stod(token.substr(1));
    } catch (...) {
        return false;
    }
    return true;
}

static inline uint32_t axis_max_speed(char axis) {
    switch (toupper(axis)) {
        case 'R':
        case 'T': return STEPPER_RT_MAXVELOCITY;
        case 'Z': return STEPPER_Z_MAXVELOCITY;
        default:  return 0;
    }
}

static void print_imu_sample(const Esp32UART::ImuSample& sample) {
    std::ios::fmtflags oldFlags = std::cout.flags();
    std::streamsize oldPrec = std::cout.precision();

    std::cout << std::fixed << std::setprecision(3)
              << "[IMU] t=" << (sample.timestampUs / 1000.0) << " ms "
              << "acc=(" << sample.ax << ", " << sample.ay << ", " << sample.az << ") m/s^2 "
              << "gyro=(" << sample.gx << ", " << sample.gy << ", " << sample.gz << ") rad/s "
              << "radial=" << sample.radialAccel << " m/s^2 "
              << "omega=" << sample.omega << " rad/s "
              << "m_corr=" << sample.correctiveMass_g << " g "
              << "ang=" << sample.correctiveAngle_deg << " deg"
              << std::endl;

    std::cout.flags(oldFlags);
    std::cout.precision(oldPrec);
}

// Representative controller for readbacks (tw_* side is fine for echo checks)
static TicController* rep_ctrl_for(char axis,
                                   TicController& tic_tw_r, TicController& tic_tw_t,
                                   TicController& tic_tw_z1) {
    switch (axis) {
        case 'R': return &tic_tw_r;
        case 'T': return &tic_tw_t;
        case 'Z': return &tic_tw_z1;
        default:  return nullptr;
    }
}

int main() {
    // ===== 1) Instantiate controllers =====
    TicController tic_tw_z1("/dev/i2c-1", 0x10, STEPPER_Z_STEPMODE,  STEPPER_Z_MAXACCELERATION,  STEPPER_Z_MAXDECELERATION,  STEPPER_Z_MAXVELOCITY,  STEPPER_Z_MAXCURRENTmA, "tic_tw_z1");
    TicController tic_tw_z2("/dev/i2c-1", 0x11, STEPPER_Z_STEPMODE,  STEPPER_Z_MAXACCELERATION,  STEPPER_Z_MAXDECELERATION,  STEPPER_Z_MAXVELOCITY,  STEPPER_Z_MAXCURRENTmA, "tic_tw_z2");
    TicController tic_tw_t ("/dev/i2c-1", 0x0F, STEPPER_RT_STEPMODE, STEPPER_RT_MAXACCELERATION, STEPPER_RT_MAXDECELERATION, STEPPER_RT_MAXVELOCITY, STEPPER_RT_MAXCURRENTmA, "tic_tw_t");
    TicController tic_tw_r ("/dev/i2c-1", 0x0E, STEPPER_RT_STEPMODE, STEPPER_RT_MAXACCELERATION, STEPPER_RT_MAXDECELERATION, STEPPER_RT_MAXVELOCITY, STEPPER_RT_MAXCURRENTmA, "tic_tw_r");
    TicController tic_cw_z1("/dev/i2c-1", 0x14, STEPPER_Z_STEPMODE,  STEPPER_Z_MAXACCELERATION,  STEPPER_Z_MAXDECELERATION,  STEPPER_Z_MAXVELOCITY,  STEPPER_Z_MAXCURRENTmA, "tic_cw_z1");
    TicController tic_cw_z2("/dev/i2c-1", 0x15, STEPPER_Z_STEPMODE,  STEPPER_Z_MAXACCELERATION,  STEPPER_Z_MAXDECELERATION,  STEPPER_Z_MAXVELOCITY,  STEPPER_Z_MAXCURRENTmA, "tic_cw_z2");
    TicController tic_cw_t ("/dev/i2c-1", 0x13, STEPPER_RT_STEPMODE, STEPPER_RT_MAXACCELERATION, STEPPER_RT_MAXDECELERATION, STEPPER_RT_MAXVELOCITY, STEPPER_RT_MAXCURRENTmA, "tic_cw_t");
    TicController tic_cw_r ("/dev/i2c-1", 0x12, STEPPER_RT_STEPMODE, STEPPER_RT_MAXACCELERATION, STEPPER_RT_MAXDECELERATION, STEPPER_RT_MAXVELOCITY, STEPPER_RT_MAXCURRENTmA, "tic_cw_r");

    vector<TicController*> all = {
        &tic_tw_z1, &tic_tw_z2, &tic_tw_t, &tic_tw_r,
        &tic_cw_z1, &tic_cw_z2, &tic_cw_t, &tic_cw_r
    };

    AxisGroup AX_R{ &tic_tw_r, &tic_cw_r };
    AxisGroup AX_T{ &tic_tw_t, &tic_cw_t };
    AxisGroup AX_Z{ &tic_tw_z1, &tic_tw_z2, &tic_cw_z1, &tic_cw_z2 };

    // Interfaces
    LED     led;
    DLPC900 dlp;
    Esp32UART uart("/dev/ttyTHS1", 115200);

    std::queue<std::string> commandQueue;
    bool executingQueue = false; // variables for when multiple commands are queued up

    // Bring motors online
    for (auto* m : all) {
        m->exitSafeStart();
        m->energize();
        m->setTargetVelocity(0);
    }

    // ===== 2) Optional: home on startup =====
    cout << "Homing R/T/Z ..." << endl;
    zeroAxisPair(tic_tw_r, tic_cw_r, HOME_DIR_R, HOME_OFF_R);
    zeroAxisPair(tic_tw_t, tic_cw_t, HOME_DIR_T, HOME_OFF_T);
    zeroAxisPair(tic_tw_z1, tic_tw_z2, tic_cw_z1, tic_cw_z2, HOME_DIR_Z, HOME_OFF_Z);
    cout << "Homing complete." << endl;

    // Projector / LED basic init
    led.configure();
    led.current(450);
    dlp.configure();

    // ===== 3) Interpreter state =====
    bool absolute_mode = true;             // G90 (default)
    double F_global = 100000.0;            // (kept as-is in your current file)
    unordered_map<char, double> F_axis = {
        {'R', F_global}, {'T', F_global}, {'Z', F_global}, {'A', 9.0} // A uses RPM
    };

    // --- readiness helper ---
    auto ensure_ready = [&](const AxisGroup& grp) {
        if (grp.a) { grp.a->clearDriverError(); grp.a->exitSafeStart(); grp.a->energize(); grp.a->resetCommandTimeout(); }
        if (grp.b) { grp.b->clearDriverError(); grp.b->exitSafeStart(); grp.b->energize(); grp.b->resetCommandTimeout(); }
        if (grp.c) { grp.c->clearDriverError(); grp.c->exitSafeStart(); grp.c->energize(); grp.c->resetCommandTimeout(); }
        if (grp.d) { grp.d->clearDriverError(); grp.d->exitSafeStart(); grp.d->energize(); grp.d->resetCommandTimeout(); }
    };


//rapid cap ceiling
    auto set_rapid_caps = [&](){
        AX_R.setMaxSpeed(STEPPER_RT_MAXVELOCITY);
        AX_T.setMaxSpeed(STEPPER_RT_MAXVELOCITY);
        AX_Z.setMaxSpeed(STEPPER_Z_MAXVELOCITY);
    };

    auto try_apply_axis_speed = [&](char axis, const AxisGroup& grp) -> bool {
        const uint32_t cap = axis_max_speed(axis);
        double req = (F_axis.count(axis) ? F_axis[axis] : F_global);

        if (req < 0.0 || req > static_cast<double>(cap)) {
            cout << "[RANGE] Axis " << axis << " feed " << req
                 << " is out of range [0, " << cap << "] ? skipping.\n";
            return false;
        }
        if (req == 0.0) {
            cout << "[WARN] Axis " << axis << " feed is 0. skipping move.\n";
            return false; // Do not proceed with a 0-speed move
        }
        grp.setMaxSpeed(static_cast<uint32_t>(req));
        return true;
    };

    auto get_axis_pos = [&](char axis)->int32_t {
        try {
            switch (axis) {
                case 'R': return tic_tw_r.getCurrentPosition();
                case 'T': return tic_tw_t.getCurrentPosition();
                case 'Z': return tic_tw_z1.getCurrentPosition();
                default:  return 0;
            }
        } catch (...) {
            cout << "[NOTE] Could not read current position for axis " << axis << ". Assuming 0 for relative math.\n";
            return 0;
        }
    };

    auto move_axis = [&](char axis, const AxisGroup& grp, int32_t target) {
        ensure_ready(grp);

        if (!try_apply_axis_speed(axis, grp)) {
            cout << "[SKIP] Move on axis " << axis << " not executed due to invalid feed.\n";
            return;
        }

        grp.setTargetPosition(target);

        TicController* c = rep_ctrl_for(axis, tic_tw_r, tic_tw_t, tic_tw_z1);
        if (c) {
            int32_t echoed_target = 0;
            try { echoed_target = c->getTargetPosition(); } catch (...) { }
            int32_t start_pos = 0;
            try { start_pos = c->getCurrentPosition(); } catch (...) { }
            cout << "[CMD] Axis " << axis << " commanded target=" << target
                 << " ; controller target=" << echoed_target
                 << " ; start pos=" << start_pos << "\n";

            using namespace std::chrono_literals;
            std::this_thread::sleep_for(150ms);

            int32_t pos_after = start_pos;
            try { pos_after = c->getCurrentPosition(); } catch (...) { }
            if (pos_after == start_pos) {
                cout << "[WARN] Axis " << axis << " position did not change ("
                     << start_pos << " -> " << pos_after << ").\n"
                     << "       Possible causes: feed=0, command timeout, safe-start, driver error, endstop engaged.\n";
            }
        } else {
            cout << "[CMD] Axis " << axis << " commanded target=" << target << "\n";
        }
    };

    auto set_axis_zero = [&](char axis) {
        switch (axis) {
            case 'R':
                tic_tw_r.haltAndSetPosition(0); tic_cw_r.haltAndSetPosition(0); break;
            case 'T':
                tic_tw_t.haltAndSetPosition(0); tic_cw_t.haltAndSetPosition(0); break;
            case 'Z':
                tic_tw_z1.haltAndSetPosition(0); tic_tw_z2.haltAndSetPosition(0);
                tic_cw_z1.haltAndSetPosition(0); tic_cw_z2.haltAndSetPosition(0);
                break;
        }
    };

    auto disable_axis = [&](char axis) {
        switch (axis) {
            case 'R':
                tic_tw_r.deenergize(); tic_cw_r.deenergize();
                break;
            case 'T':
                tic_tw_t.deenergize(); tic_cw_t.deenergize();
                break;
            case 'Z':
                tic_tw_z1.deenergize(); tic_tw_z2.deenergize();
                tic_cw_z1.deenergize(); tic_cw_z2.deenergize();
                break;
            default:
                break;
        }
    };

    auto motors_enable = [&](){
        for (auto* m : all){ m->energize(); }
    };
    auto motors_disable = [&](const std::vector<char>& axes = {}){
        if (axes.empty()) {
            disable_axis('R');
            disable_axis('T');
        } else {
            for (char axis : axes) {
                disable_axis(static_cast<char>(std::toupper(axis)));
            }
        }
        uart.setThetaVelocity(0);
    };

    // ===== 4) Command loop =====
    cout << "G-code ready. Examples: `G0 R100 T100 Z100`, `G1 Z-200 FR120000`, `G33 A9`, `M114`, `M112`.\n";
    cout << "Comments with ';' are ignored. Ctrl-D to exit.\n";
    
    string raw;
    while (true) {
        cout << "> " << flush;
        if (!std::getline(cin, raw)) break; // User pressed Ctrl-D
        string line = strip_comment_and_trim(raw);
        if (line.empty()) continue;
        commandQueue.push(line);
        if (executingQueue) {
            cout << "Command queued.\n";
            continue;
        }
        executingQueue = true;
        while (!commandQueue.empty())
        {
            // Check for abort *before* processing a new command
            if (abort_requested()) {
                 cout << "ABORT: Clearing command queue.\n";
                 std::queue<std::string> empty; //Nuke the queue
                 std::swap(commandQueue, empty);
                 // Trigger emergency stop
                 motors_disable();
                 dlp.setVideoSource(DLPC900_IT6535MODE_POWERDOWN);
                 led.stop();
                 break; 
            }

            string cmd_from_queue = commandQueue.front();
            commandQueue.pop();
            cout << "Executing: " << cmd_from_queue << "\n";

            // Tokenize
            istringstream iss(cmd_from_queue);
            string head; iss >> head;
            if (head.empty()) continue; // Skip empty commands from queue
            std::transform(head.begin(), head.end(), head.begin(), ::toupper);

            auto bail_if_abort = [&](){
                if (abort_requested()) throw runtime_error("EMERGENCY STOP (aborted)");
            };
            auto parse_axis_args = [&](istringstream& stream) {
                vector<char> axes;
                string token;
                while (stream >> token) {
                    for (char ch : token) {
                        ch = static_cast<char>(std::toupper(ch));
                        if (ch == 'R' || ch == 'T' || ch == 'Z' || ch == 'A') {
                            axes.push_back(ch);
                        }
                    }
                }
                return axes;
            };

            try {
                // ===== M-codes =====
                if (head[0] == 'M') {
                    int mnum = stoi(head.substr(1));
                    switch (mnum) {
                        case 17: motors_enable(); cout << "M17: Motors enabled.\n"; break;
                        case 18: {
                            auto axes = parse_axis_args(iss);
                            motors_disable(axes);
                            cout << "M18: Motors disabled.\n";
                            break;
                        }
                        case 112:
                            cout << "M112: EMERGENCY STOP.\n";
                            motors_disable(std::vector<char>{'R','T','Z'});
                            dlp.setVideoSource(DLPC900_IT6535MODE_POWERDOWN);
                            led.stop();
                            return 0; // This will exit the program
                        case 114: { // report positions/targets
                            auto report = [&](const char* name, TicController& c) {
                                try {
                                    auto cur = c.getCurrentPosition();
                                    auto tgt = c.getTargetPosition();
                                    cout << name << "  cur=" << cur << "  tgt=" << tgt << "\n";
                                } catch (const std::exception& e) {
                                    cout << name << "  [read error] " << e.what() << "\n";
                                }
                            };
                            cout << "---- M114 ----\n";
                            report("R_tw", tic_tw_r); report("R_cw", tic_cw_r);
                            report("T_tw", tic_tw_t); report("T_cw", tic_cw_t);
                            report("Z_tw1", tic_tw_z1); report("Z_tw2", tic_tw_z2);
                            report("Z_cw1", tic_cw_z1); report("Z_cw2", tic_cw_z2);
                            cout << "--------------\n";
                            break;
                        }
                        case 116: { // M116: show current feed rates per axis
                            auto getF = [&](char k, double fallback)->double {
                                auto it = F_axis.find(k);
                                return (it == F_axis.end()) ? fallback : it->second;
                            };
                            double fr = getF('R', F_global);
                            double ft = getF('T', F_global);
                            double fz = getF('Z', F_global);
                            double fa = getF('A', 0.0); // RPM for A

                            cout << "---- M116: Feed Rates ----\n";
                            cout << "F (global): " << F_global << "  [applies to R/T/Z unless overridden]\n";
                            cout << "FR (R)    : " << fr << "       [range 0 .. " << STEPPER_RT_MAXVELOCITY << "]\n";
                            cout << "FT (T)    : " << ft << "       [range 0 .. " << STEPPER_RT_MAXVELOCITY << "]\n";
                            cout << "FZ (Z)    : " << fz << "       [range 0 .. " << STEPPER_Z_MAXVELOCITY  << "]\n";
                            cout << "FA (A)    : " << fa << " rpm   [range " << A_RPM_MIN << " .. " << A_RPM_MAX << " rpm]\n";
                            cout << "Note: R/T/Z use setMaxSpeed(feed) then setTargetPosition(...). A uses setThetaVelocity(pps).\n";
                            cout << "---------------------------\n";
                            break;
                        }
                        case 30: {//M30 : End program
                            cout << "M30: Program complete. Exiting G-Code Mode.\n";
                            motors_disable(); 
                            dlp.setVideoSource(DLPC900_IT6535MODE_POWERDOWN);
                            led.stop();
                            restore_terminal();
                            return 0; // This will exit the program
                        }
                        case 200: led.configure();led.current(450);dlp.configure(); cout << "M200: Projector ON (configured).\n"; break;
                        case 205: {
                            double current_ma = -1.0;
                            string token;
                            while (iss >> token) {
                                if (token.empty()) continue;
                                if (token[0] == 'S' || token[0] == 's') {
                                    try {
                                        current_ma = stod(token.substr(1));
                                    } catch (...) {
                                        current_ma = -1.0;
                                    }
                                }
                            }
                            if (current_ma < 0) {
                                cout << "M205: Provide current via S parameter (e.g., M205 S450).\n";
                                break;
                            }
                            if (current_ma > 30000) {
                                cout << "M205: Requested " << current_ma << " mA exceeds 30000 mA limit.\n";
                                break;
                            }
                            led.current(static_cast<int>(current_ma));
                            cout << "M205: LED current set to " << static_cast<int>(current_ma) << " mA.\n";
                            break;
                        }
                        case 201: dlp.setVideoSource(DLPC900_IT6535MODE_POWERDOWN);led.stop(); cout << "M201: Projector OFF.\n"; break;
                        case 202: system("xdotool search --name ProjectorVideo windowactivate --sync key space"); cout << "M202: Projector video PLAY/TOGGLE.\n"; break;
                        case 203: system("xdotool search --name ProjectorVideo windowactivate --sync key space"); cout << "M203: Projector video PAUSE/TOGGLE.\n"; break;
                        case 204: system("xdotool search --name ProjectorVideo windowactivate --sync key home");  cout << "M204: Projector video RESTART.\n"; break;
                        case 210: {
                            Esp32UART::ImuSample sample;
                            if (uart.getImuSample(sample)) {
                                print_imu_sample(sample);
                            } else {
                                cout << "[IMU] Failed to retrieve sample.\n";
                            }
                            break;
                        }
                        case 211: {
                            cout << "M211: Requesting IMU calibration...\n";
                            if (uart.requestImuCalibration()) {
                                cout << "[IMU] Calibration complete.\n";
                            } else {
                                cout << "[IMU] Calibration failed or timed out.\n";
                            }
                            break;
                        }
                        default:  cerr << "Unknown M" << mnum << "\n"; break;
                    }
                    continue; // M-codes don't need to wait for motion
                }

                // ===== G-codes =====
                if (head[0] != 'G') {
                    cerr << "Unknown command head: " << head << "\n";
                    continue;
                }

                int gnum = stoi(head.substr(1));

                // collect remaining tokens as key/values
                vector<pair<char,double>> params;
                string tok;
                while (iss >> tok) {
                    if (tok.empty()) continue;
                    tok[0] = static_cast<char>(toupper(tok[0]));
                    if (tok[0] == 'F') {
                        if ((tok.size() > 1) && (isdigit(tok[1]) || tok[1] == '-')) {
                            // Case 1: Global F word (F100000)
                            try {
                                double v = stod(tok.substr(1));
                                F_global = v;
                                F_axis['R'] = F_axis['T'] = F_axis['Z'] = F_global;
                                cout << "F: Global feed set to " << v << "\n";
                            } catch (...) {
                                cerr << "Ignoring invalid F token: " << tok << "\n";
                            }
                        } else if (tok.size() >= 2 && isalpha(tok[1])) {
                            // Case 2: Per-axis F word (FR10000, FA9)
                            char ax = static_cast<char>(toupper(tok[1]));
                            double fv = 0.0;
                            try { fv = stod(tok.substr(2)); } catch(...) { fv = 0.0; }
                            
                            if (ax == 'A') {
                                if (fv < A_RPM_MIN || fv > A_RPM_MAX) {
                                    cout << "[RANGE] FA " << fv << " RPM not in ["
                                         << A_RPM_MIN << ", " << A_RPM_MAX << "] ? ignoring.\n";
                                } else {
                                    F_axis['A'] = fv;
                                    cout << "FA: rotation feed set to " << fv << " RPM\n";
                                }
                            } else {
                                const uint32_t cap = axis_max_speed(ax);
                                if (fv < 0.0 || fv > static_cast<double>(cap)) {
                                    cout << "[RANGE] F" << ax << " " << fv
                                         << " not in [0, " << cap << "] ? ignoring.\n";
                                } else {
                                    F_axis[ax] = fv;
                                    cout << "F" << ax << ": feed set to " << fv << "\n";
                                }
                            }
                        } else {
                             cerr << "Ignoring malformed F token: " << tok << "\n";
                        }
                        continue; // F-words are not G-code params, so skip to next token
                    }

                    // --- Default parameter parsing (R, T, Z, etc.) ---
                    char k; double v;
                    if (parse_param(tok, k, v)) {
                        params.emplace_back(k, v);
                    } else {
                        cerr << "Ignoring token: " << tok << "\n";
                    }
                }
                switch (gnum) {
                    case 0: { // G0 rapid at axis caps
                        bool hasR=false, hasT=false, hasZ=false;
                        double Rv=0, Tv=0, Zv=0;

                        for (auto& kv : params) {
                            switch (kv.first) {
                                case 'R': hasR=true; Rv=kv.second; break;
                                case 'T': hasT=true; Tv=kv.second; break;
                                case 'Z': hasZ=true; Zv=kv.second; break;
                                default: break;
                            }
                        }

                        // R
                        if (hasR) {
                            int32_t target = absolute_mode ? static_cast<int32_t>(Rv)
                                                        : get_axis_pos('R') + static_cast<int32_t>(Rv);
                            ensure_ready(AX_R);
                            AX_R.setMaxSpeed(axis_max_speed('R'));   // force rapid cap
                            AX_R.setTargetPosition(target);          // go!
                            cout << "[G0] R rapid -> " << target
                                << " @ " << axis_max_speed('R') << "\n";
                        }

                        // T
                        if (hasT) {
                            int32_t target = absolute_mode ? static_cast<int32_t>(Tv)
                                                        : get_axis_pos('T') + static_cast<int32_t>(Tv);
                            ensure_ready(AX_T);
                            AX_T.setMaxSpeed(axis_max_speed('T'));   // force rapid cap
                            AX_T.setTargetPosition(target);
                            cout << "[G0] T rapid -> " << target
                                << " @ " << axis_max_speed('T') << "\n";
                        }

                        // Z
                        if (hasZ) {
                            int32_t target = absolute_mode ? static_cast<int32_t>(Zv)
                                                        : get_axis_pos('Z') + static_cast<int32_t>(Zv);
                            ensure_ready(AX_Z);
                            AX_Z.setMaxSpeed(axis_max_speed('Z'));   // force rapid cap
                            AX_Z.setTargetPosition(target);
                            cout << "[G0] Z rapid -> " << target
                                << " @ " << axis_max_speed('Z') << "\n";
                        }
                        break;
                    }

                    case 1: { // G1 linear at per-axis feed (validations in move_axis/try_apply_axis_speed)
                        bool hasR=false, hasT=false, hasZ=false;
                        double Rv=0, Tv=0, Zv=0;

                        for (auto& kv : params) {
                            switch (kv.first) {
                                case 'R': hasR=true; Rv=kv.second; break;
                                case 'T': hasT=true; Tv=kv.second; break;
                                case 'Z': hasZ=true; Zv=kv.second; break;
                                default: break;
                            }
                        }

                        if (hasR) {
                            int32_t target = absolute_mode ? static_cast<int32_t>(Rv)
                                                        : get_axis_pos('R') + static_cast<int32_t>(Rv);
                            move_axis('R', AX_R, target);   // uses per-axis feed / checks
                        }
                        if (hasT) {
                            int32_t target = absolute_mode ? static_cast<int32_t>(Tv)
                                                        : get_axis_pos('T') + static_cast<int32_t>(Tv);
                            move_axis('T', AX_T, target);
                        }
                        if (hasZ) {
                            int32_t target = absolute_mode ? static_cast<int32_t>(Zv)
                                                        : get_axis_pos('Z') + static_cast<int32_t>(Zv);
                            move_axis('Z', AX_Z, target);
                        }
                        break;
                    }

                    case 4: { // G4 dwell: Pms
                        double Pms = 0;
                        for (auto& kv : params) if (kv.first=='P') Pms = kv.second;
                        int ms = static_cast<int>(max(0.0, Pms));
                        cout << "G4 dwell " << ms << " ms\n";
                        std::this_thread::sleep_for(std::chrono::milliseconds(ms));
                        break;
                    }

                    case 5: { // G5 wait until RPM reached (CUSTOM, simple dwell)
                        double target_rpm = (F_axis.count('A') ? F_axis['A'] : 0.0);
                        if (target_rpm < A_RPM_MIN || target_rpm > A_RPM_MAX) {
                            cout << "[RANGE] A feed " << target_rpm << " RPM not in ["
                                << A_RPM_MIN << ", " << A_RPM_MAX
                                << "] ? cannot wait, value invalid.\n";
                        } else {
                            cout << "G5: wait for A steady-state (" << target_rpm << " rpm)\n";
                            std::this_thread::sleep_for(std::chrono::milliseconds(1000));
                        }
                        break;
                    }

                    case 6: { // G6 wait until print completion (stub)
                        cout << "G6: wait until print completion (stub)\n";
                        break;
                    }

                    case 28: { // G28 homing ? ensure max speeds before homing
                        cout << "G28: homing R/T/Z\n";
                        // Force caps so homing is never limited by prior G1 feeds
                        AX_R.setMaxSpeed(axis_max_speed('R'));
                        AX_T.setMaxSpeed(axis_max_speed('T'));
                        AX_Z.setMaxSpeed(axis_max_speed('Z'));
                        zeroAxisPair(tic_tw_r, tic_cw_r, HOME_DIR_R, HOME_OFF_R);
                        zeroAxisPair(tic_tw_t, tic_cw_t, HOME_DIR_T, HOME_OFF_T);
                        zeroAxisPair(tic_tw_z1, tic_tw_z2, tic_cw_z1, tic_cw_z2, HOME_DIR_Z, HOME_OFF_Z);
                        break;
                    }

                    case 33: { // G33 A<rpm> continuous rotation
                        double rpm = 0;
                        for (auto& kv : params) if (kv.first=='A') rpm = kv.second;
                        if (rpm < A_RPM_MIN || rpm > A_RPM_MAX) {
                            cout << "[RANGE] G33 A " << rpm << " RPM not in ["
                                << A_RPM_MIN << ", " << A_RPM_MAX
                                << "] ? skipping.\n";
                        } else {
                            int32_t pps = rpm_to_pps(rpm);
                            uart.setThetaVelocity(pps);
                            F_axis['A'] = rpm; // remember
                            cout << "G33: A -> " << rpm << " rpm (pps=" << pps << ")\n";
                        }
                        break;
                    }

                    case 90: absolute_mode = true;  cout << "G90: absolute positioning\n"; break;
                    case 91: absolute_mode = false; cout << "G91: relative positioning\n"; break;

                    case 92: { // G92 set current position to 0 (per axis)
                        bool any=false;
                        for (auto& kv : params) {
                            if (kv.first=='R' || kv.first=='T' || kv.first=='Z') {
                                set_axis_zero(kv.first);
                                cout << "G92: zeroed axis " << kv.first << "\n";
                                any=true;
                            }
                        }
                        if (!any) {
                            set_axis_zero('R'); set_axis_zero('T'); set_axis_zero('Z');
                            cout << "G92: zeroed R/T/Z\n";
                        }
                        break;
                    }

                    default:
                        cerr << "Unknown/unsupported G" << gnum << "\n";
                        break;
                }
                bail_if_abort();
            } catch (const std::exception& e) {
                cerr << "!! ERROR: " << e.what() << "\n";
                // This will stop on an error. You could 'continue'
                // to the next command instead if you prefer.
            }

            bool wait_loop_error = false; // Add a flag
            try {
                while (tic_tw_r.getCurrentPosition() != tic_tw_r.getTargetPosition() ||
                       tic_tw_t.getCurrentPosition() != tic_tw_t.getTargetPosition() ||
                       tic_tw_z1.getCurrentPosition() != tic_tw_z1.getTargetPosition())
                {
                    if (abort_requested())
                    {
                        cout << "ABORT: Halting all motion.\n";
                        // Send an immediate halt command
                        AX_R.haltAndHold();
                        AX_T.haltAndHold();
                        AX_Z.haltAndHold();
                        break; // Exit the wait loop
                    }
                    
                    // Sleep for 20ms to avoid busy-waiting
                    std::this_thread::sleep_for(std::chrono::milliseconds(20));
                }
            } catch (const std::exception& e) {
                cerr << "!! CRITICAL I2C ERROR during wait loop: " << e.what() << "\n";
                cerr << "!! Halting motion and clearing queue for safety. !!\n";
                AX_R.haltAndHold();
                AX_T.haltAndHold();
                AX_Z.haltAndHold();
                wait_loop_error = true; // Set the flag
            }

            // If the error flag was set, nuke the queue and break
            if (wait_loop_error) {
                 std::queue<std::string> empty; // Nuke the queue
                 std::swap(commandQueue, empty);
                 break; // Break out of the 'while (!commandQueue.empty())' loop
            }
            
            cout << "--- Command complete ---" << endl;

        } // --- End of CHANGE 4 (processor loop) ---

        // --- CHANGE 8: Reset the flag ---
        // The queue is empty, so we are no longer processing.
        executingQueue = false;
        
        // Only print "ready" if the queue just finished
        if (!line.empty()) {
            cout << "Queue empty. Ready for new commands.\n";
        }

    }

    // ===== 5) Cleanup =====
    cout << "Shutting down...\n";
    uart.setThetaVelocity(0);
    dlp.setVideoSource(DLPC900_IT6535MODE_POWERDOWN);
    led.stop();
    for (auto* m : all) m->deenergize();
    restore_terminal();
    return 0;
}
