#pragma once

#include <cstdint>

// Initializes the raw terminal listener that watches for space/enter presses.
void init_key_listener();

// Returns true if an abort (either from keyboard or software) has been
// requested. Long-running routines should poll this regularly.
bool abort_requested();

// Resets the abort flag after the current interruption has been handled.
void clear_abort_request();

// Used by software components (e.g., GUI-issued E-Stop) to force an abort
// without requiring a physical keypress.
void request_abort();

// Returns true if an ENTER press was detected and clears that flag.
bool consume_enter();

// Sleeps in small increments while checking the abort flag.
bool wait_or_abort(int total_ms, int chunk_ms = 50);

// Restores the terminal mode that existed before init_key_listener().
void restore_terminal();

// Homing helpers for paired axes.
void zeroAxisPair(class TicController &A,
                  class TicController &B,
                  uint8_t homeDir,
                  int32_t finalOffset);

void zeroAxisPair(class TicController &A,
                  class TicController &B,
                  class TicController &C,
                  class TicController &D,
                  uint8_t homeDir,
                  int32_t finalOffset);
