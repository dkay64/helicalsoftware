#include "HeliCalHelper.h"
#include <termios.h>
#include <fcntl.h>
#include <unistd.h>
#include <cstdlib>
#include <cmath>
#include <thread>
#include <atomic>
#include <chrono>

static std::atomic<bool> _abort_flag{false};
static std::atomic<bool> _enter_flag{false};
static struct termios _orig_term;

// invoked once at startup
void init_key_listener() {
    // stash and switch to raw mode
    tcgetattr(STDIN_FILENO, &_orig_term);
    termios raw = _orig_term;
    raw.c_lflag &= ~(ICANON | ECHO);
    tcsetattr(STDIN_FILENO, TCSANOW, &raw);

    std::thread([](){
        while (true) {
            int c = getchar();
            if (c == ' ') {
                _abort_flag.store(true);
            } else if (c == '\n' || c == '\r') {
                _enter_flag.store(true);
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(5));
        }
    }).detach();
}

bool abort_requested() {
    return _abort_flag.load();
}

void request_abort() {
    _abort_flag.store(true);
}

void clear_abort_request() {
    _abort_flag.store(false);
}

bool consume_enter() {
    if (_enter_flag.load()) {
        _enter_flag.store(false);
        return true;
    }
    return false;
}

bool wait_or_abort(int total_ms, int chunk_ms) {
    int waited = 0;
    while (waited < total_ms) {
        if (abort_requested()) {
            return false;
        }
        int step = std::min(chunk_ms, total_ms - waited);
        usleep(step * 1000);
        waited += step;
    }
    return true;
}

void restore_terminal() {
    // put back original termios so shell works
    tcsetattr(STDIN_FILENO, TCSANOW, &_orig_term);
}

// --- zeroing routines (unchanged) ---------------------------------------------

void zeroAxisPair(TicController &A, TicController &B,
                  uint8_t homeDir,
                  int32_t finalOffset)
{
    A.goHome(homeDir);
    B.goHome(homeDir);
    while (true) {
        if (abort_requested()) throw std::runtime_error("User abort");
        auto fA = A.getVariable(0x01);
        auto fB = B.getVariable(0x01);
        bool homing = ((fA & (1 << 4)) || (fB & (1 << 4)));
        if (!homing) break;
        usleep(100000);
    }
    A.setTargetPosition(finalOffset);
    B.setTargetPosition(finalOffset);
    while ((std::abs(A.getCurrentPosition() - finalOffset) > 1) ||
           (std::abs(B.getCurrentPosition() - finalOffset) > 1))
    {
        if (abort_requested()) throw std::runtime_error("User abort");
        usleep(500000);
    }
}

void zeroAxisPair(TicController &A, TicController &B,
                  TicController &C, TicController &D,
                  uint8_t homeDir,
                  int32_t finalOffset)
{
    A.goHome(homeDir);
    B.goHome(homeDir);
    C.goHome(homeDir);
    D.goHome(homeDir);
    while (true) {
        if (abort_requested()) throw std::runtime_error("User abort");
        auto fA = A.getVariable(0x01);
        auto fB = B.getVariable(0x01);
        auto fC = C.getVariable(0x01);
        auto fD = D.getVariable(0x01);
        bool homing = ((fA & (1 << 4)) || (fB & (1 << 4)) ||
                       (fC & (1 << 4)) || (fD & (1 << 4)));
        if (!homing) break;
        usleep(100000);
    }
    A.setTargetPosition(finalOffset);
    B.setTargetPosition(finalOffset);
    C.setTargetPosition(finalOffset);
    D.setTargetPosition(finalOffset);
    while ((std::abs(A.getCurrentPosition() - finalOffset) > 1) ||
           (std::abs(B.getCurrentPosition() - finalOffset) > 1) ||
           (std::abs(C.getCurrentPosition() - finalOffset) > 1) ||
           (std::abs(D.getCurrentPosition() - finalOffset) > 1))
    {
        if (abort_requested()) throw std::runtime_error("User abort");
        usleep(500000);
    }
}
