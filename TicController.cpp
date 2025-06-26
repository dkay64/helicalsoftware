#include "TicController.h"
#include <fcntl.h>
#include <linux/i2c-dev.h>
#include <linux/i2c.h>
#include <sys/ioctl.h>
#include <unistd.h>
#include <stdexcept>
#include <iostream>

TicController::TicController(const char* i2c_device, uint8_t i2c_address)
{
    this->i2c_address = i2c_address;

    // Open I2C device
    file = open(i2c_device, O_RDWR);
    if (file < 0)
    {
        throw std::runtime_error("Failed to open the I2C bus");
    }

    // Set the I2C slave address
    if (ioctl(file, I2C_SLAVE, i2c_address) < 0)
    {
        throw std::runtime_error("Failed to acquire bus access and/or talk to slave");
    }
}

TicController::TicController(const char* i2c_device, uint8_t i2c_address, 
                             uint8_t step_mode, uint32_t max_acceleration, 
                             uint32_t max_deceleration, uint32_t max_velocity,
                             uint32_t max_current_mA)
    : TicController(i2c_device, i2c_address)  // Delegate to the basic constructor
{
    // Validate the step mode parameter (should be 0-9)
    if (step_mode > 9)
    {
        throw std::invalid_argument("Step mode must be between 0 and 9");
    }
    
    // Store and set the microstepping mode.
    // For example, a value of 3 corresponds to 1/8 step mode.
    this->step_mode = step_mode;
    setStepMode(step_mode);
    
    // Set other motion parameters.
    setMaxAcceleration(max_acceleration); //microsteps per 100 s^2
    setMaxDeceleration(max_deceleration);
    setMaxSpeed(max_velocity); //microsteps per 10,000s
    
    // Convert the desired current (in mA) to a 7-bit value.
    // The range is 0 mA to 9095 mA mapped to 0–127.
    // Each unit is ˜ 9095 / 127 ˜ 71.65 mA.
    // For example, for 2000 mA:
    //     (2000 / 9095.0) * 127 ˜ 27.89, so truncating gives 27.
    uint8_t current_value = static_cast<uint8_t>((max_current_mA / 9095.0) * 127);
    
    // Set the current limit using the converted 7-bit value.
    setCurrentLimit(current_value);
}

TicController::~TicController()
{
    close(file);  // Close the I2C file when done
}

void TicController::writeCommand(uint8_t command, int32_t value)
{
    uint8_t buffer[5] = {
        command,
        (uint8_t)(value >> 0  & 0xFF),
        (uint8_t)(value >> 8  & 0xFF),
        (uint8_t)(value >> 16 & 0xFF),
        (uint8_t)(value >> 24 & 0xFF)
    };

    struct i2c_msg message = { i2c_address, 0, sizeof(buffer), buffer };
    struct i2c_rdwr_ioctl_data ioctl_data = { &message, 1 };

    if (ioctl(file, I2C_RDWR, &ioctl_data) != 1)
    {
        throw std::runtime_error("Failed to send I2C command");
    }
}

void TicController::exitSafeStart() { writeCommand(0x83); }
void TicController::enterSafeStart() { writeCommand(0x8F); }
void TicController::resetCommandTimeout() { writeCommand(0x85); }
void TicController::deenergize() { writeCommand(0x86); }
void TicController::energize() { writeCommand(0x85); }
void TicController::reset() { writeCommand(0xB0); }
void TicController::clearDriverError() { writeCommand(0x8A); }
void TicController::setTargetPosition(int32_t position) { writeCommand(0xE0, position); }
void TicController::setTargetVelocity(int32_t velocity) { writeCommand(0xE3, velocity); }
void TicController::haltAndSetPosition(int32_t position) { writeCommand(0xEC, position); }
void TicController::haltAndHold() { writeCommand(0x89); }
void TicController::goHome(uint8_t direction) { writeCommand(0x97, direction); }
void TicController::setMaxSpeed(uint32_t speed) { writeCommand(0xE6, speed); }
void TicController::setStartingSpeed(uint32_t speed) { writeCommand(0xE5, speed); }
void TicController::setMaxAcceleration(uint32_t acceleration) { writeCommand(0xEA, acceleration); }
void TicController::setMaxDeceleration(uint32_t deceleration) { writeCommand(0xE9, deceleration); }

// setStepMode expects an integer value between 0 and 9.
// For example:
//   0: Full step (1)
//   1: Half step (2)
//   2: 1/4 step (4)
//   3: 1/8 step (8)
//   4: 1/16 step (16)
//   5: 1/32 step (32)
//   6: 1/64 step (64)
//   7: 1/128 step (128)
//   8: 1/256 step (256)
//   9: 1/512 step (512)
void TicController::setStepMode(uint8_t mode) { writeCommand(0x94, mode); }

// setCurrentLimit now accepts an unsigned 7-bit value (0-127)
// that is derived from the desired current limit in mA.
void TicController::setCurrentLimit(uint8_t current) { writeCommand(0x91, current); }

void TicController::setDecayMode(uint8_t mode) { writeCommand(0x92, mode); }
void TicController::setAGCOption(uint8_t option) { writeCommand(0x98, option); }
void TicController::setCommandTimeout(uint32_t timeout_ms)
{
    writeCommand(0xA3, (0x09 << 24) | timeout_ms);
}

int32_t TicController::readVariable(uint8_t variable_command)
{
    uint8_t command[] = { 0xA1, variable_command };
    uint8_t buffer[4];

    struct i2c_msg messages[] = {
        { i2c_address, 0, sizeof(command), command },
        { i2c_address, I2C_M_RD, sizeof(buffer), buffer }
    };

    struct i2c_rdwr_ioctl_data ioctl_data = { messages, 2 };

    if (ioctl(file, I2C_RDWR, &ioctl_data) != 2)
    {
        throw std::runtime_error("Failed to read I2C variable");
    }

    return buffer[0] | (buffer[1] << 8) | (buffer[2] << 16) | (buffer[3] << 24);
}

int32_t TicController::getCurrentPosition() { return readVariable(0x22); }
int32_t TicController::getTargetPosition() { return readVariable(0x0A); }
int32_t TicController::getCurrentVelocity() { return readVariable(0x26); }
int32_t TicController::getTargetVelocity() { return readVariable(0x0E); }

uint8_t TicController::getPlanningMode()
{
    uint8_t operation_state = readVariable(0x09);
    return (operation_state & 0x01) ? 2 : 1;
}

int32_t TicController::getVariable(uint8_t variable) { return readVariable(variable); }
int32_t TicController::getVariableAndClearErrors(uint8_t variable) { return readVariable(variable); }
int32_t TicController::getSetting(uint8_t setting) { return readVariable(setting); }
