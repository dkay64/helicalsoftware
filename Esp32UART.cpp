#include "Esp32UART.h"
#include <fcntl.h>
#include <unistd.h>
#include <stdexcept>
#include <cstring>
#include <termios.h>
#include <errno.h>
#include <sys/ioctl.h>
#include <sstream>
#include <iostream>
#include <iomanip>
#include <unistd.h>

// --- Command Definitions ---
// Encoder Commands (0x10)
#define CMD_ENCODER_POSITION 0x10
#define ENCODER_ALL          0xFF

// DC Driver Commands (0x20)
#define CMD_DC_DRIVER        0x20
#define DC_SUB_PWM           0x01
#define DC_SUB_DIR           0x02

// Theta Zeroing Commands (0x40)
#define CMD_THETA_ZERO       0x40
#define THETA_ZERO_START     0x01
#define THETA_ZERO_STATUS    0x02
#define THETA_ZERO_READ      0x03

// Theta Velocity Commands (0x30)
// This command sends 6 bytes: Byte 0 = CMD_THETA_VEL,
// Byte 1 = THETA_VEL_SET, Bytes 2-5 = 32-bit little-endian velocity.
#define CMD_THETA_VEL        0x30
#define THETA_VEL_SET        0x01

Esp32UART::Esp32UART(const std::string &uartDevice, int baudRate)
    : device(uartDevice), baud(baudRate)
{
    uartFd = open(device.c_str(), O_RDWR | O_NOCTTY);
    if(uartFd < 0) {
        throw std::runtime_error("Failed to open UART device: " + device + " Error: " + std::string(strerror(errno)));
    }
    if(fcntl(uartFd, F_SETFL, 0) < 0) {
        throw std::runtime_error("Failed to set UART fd flags: " + std::string(strerror(errno)));
    }
    tcflush(uartFd, TCIOFLUSH);
    struct termios options;
    if(tcgetattr(uartFd, &options) != 0) {
        throw std::runtime_error("Failed to get UART attributes: " + std::string(strerror(errno)));
    }
    cfsetispeed(&options, baudRate);
    cfsetospeed(&options, baudRate);
    options.c_cflag |= (CLOCAL | CREAD);
    options.c_cflag &= ~CRTSCTS;
    options.c_cflag &= ~PARENB;
    options.c_cflag &= ~CSTOPB;
    options.c_cflag &= ~CSIZE;
    options.c_cflag |= CS8;
    options.c_lflag &= ~(ICANON | ECHO | ECHOE | ISIG);
    options.c_oflag &= ~OPOST;
    options.c_cc[VMIN] = 0;
    options.c_cc[VTIME] = 1; // 100 ms timeout
    if(tcsetattr(uartFd, TCSANOW, &options) != 0) {
        throw std::runtime_error("Failed to set UART attributes: " + std::string(strerror(errno)));
    }
}

Esp32UART::~Esp32UART() {
    if(uartFd >= 0)
        close(uartFd);
}

// Modified writeCommand function to always send 6 bytes.
// For commands that originally use 3 bytes, the extra 3 bytes are set to 0.
void Esp32UART::writeCommand(uint8_t command, uint8_t subcommand, uint8_t value) {
    tcflush(uartFd, TCIFLUSH);
    uint8_t buffer[6] = {command, subcommand, value, 0, 0, 0};
    ssize_t written = write(uartFd, buffer, sizeof(buffer));
    if(written != sizeof(buffer))
        throw std::runtime_error("Failed to write UART command");
}

int32_t Esp32UART::getEncoderPosition(uint8_t encoder) {
    if(encoder >= 5)
        throw std::invalid_argument("Encoder index must be between 0 and 4");
    writeCommand(CMD_ENCODER_POSITION, encoder, 0x00);
    uint8_t buffer[sizeof(int32_t)] = {0};
    ssize_t n_read = read(uartFd, buffer, sizeof(buffer));
    int32_t pos = 0;
    memcpy(&pos, buffer, (n_read < (ssize_t)sizeof(pos)) ? (size_t)n_read : sizeof(pos));
    return pos;
}

void Esp32UART::getAllEncoderPositions(int32_t positions[5]) {
    writeCommand(CMD_ENCODER_POSITION, ENCODER_ALL, 0x00);
    uint8_t buffer[sizeof(int32_t) * 5] = {0};
    ssize_t n_read = read(uartFd, buffer, sizeof(buffer));
    memcpy(positions, buffer, (n_read < (ssize_t)sizeof(buffer)) ? (size_t)n_read : sizeof(buffer));
}

void Esp32UART::setDcDriverPwm(uint8_t pwm_val) {
    writeCommand(CMD_DC_DRIVER, DC_SUB_PWM, pwm_val);
}

void Esp32UART::setDcDriverDir(bool dir_val) {
    uint8_t value = (dir_val ? 1 : 0);
    writeCommand(CMD_DC_DRIVER, DC_SUB_DIR, value);
}

// Theta Zeroing commands
void Esp32UART::startThetaZero() {
    writeCommand(CMD_THETA_ZERO, THETA_ZERO_START, 0x00);
}

bool Esp32UART::isThetaZeroed() {
    writeCommand(CMD_THETA_ZERO, THETA_ZERO_STATUS, 0x00);
    uint8_t status = 0;
    ssize_t n_read = 0;
    const uint32_t max_wait_ms = 500;
    uint32_t waited_ms = 0;
    while ((n_read != sizeof(status)) && (waited_ms < max_wait_ms)) {
        usleep(10000);
        n_read = read(uartFd, &status, sizeof(status));
        waited_ms += 10;
    }
    return (n_read == sizeof(status) && status != 0);
}

int32_t Esp32UART::getThetaZeroMeasurement() {
    writeCommand(CMD_THETA_ZERO, THETA_ZERO_READ, 0x00);
    int32_t measured = 0;
    ssize_t n_read = read(uartFd, &measured, sizeof(measured));
    if(n_read != sizeof(measured))
        throw std::runtime_error("Failed to read theta measurement");
    return measured;
}

void Esp32UART::waitForThetaZeroComplete() {
    uint8_t msg = 0;
    ssize_t n_read = 0;
    const uint32_t max_wait_ms = 20000;
    uint32_t waited_ms = 0;
    while (waited_ms < max_wait_ms) {
         n_read = read(uartFd, &msg, sizeof(msg));
         if(n_read == sizeof(msg) && msg != 0)
              return;
         std::cout << "Waited ms: " << waited_ms << std::endl;
         usleep(200000);
         waited_ms += 200;
    }
    throw std::runtime_error("Timeout waiting for theta zero completion message");
}

// Theta Velocity command
// Sends a 6-byte command: Byte 0 = CMD_THETA_VEL, Byte 1 = THETA_VEL_SET,
// followed by the 32-bit velocity (pulses per second) in little-endian.
void Esp32UART::setThetaVelocity(int32_t velocity) {
    uint8_t cmd[6];
    cmd[0] = CMD_THETA_VEL;
    cmd[1] = THETA_VEL_SET;
    cmd[2] = velocity & 0xFF;
    cmd[3] = (velocity >> 8) & 0xFF;
    cmd[4] = (velocity >> 16) & 0xFF;
    cmd[5] = (velocity >> 24) & 0xFF;
    tcflush(uartFd, TCIFLUSH);
    ssize_t written = write(uartFd, cmd, 6);
    if(written != 6)
        throw std::runtime_error("Failed to write theta velocity command");
    /*
    uint8_t ack = 0;
    ssize_t n_read = 0;
    const uint32_t max_wait_ms = 500;
    uint32_t waited_ms = 0;
    while ((n_read != sizeof(ack)) && (waited_ms < max_wait_ms)) {
        usleep(10000);
        n_read = read(uartFd, &ack, sizeof(ack));
        waited_ms += 10;
    }
    if(n_read != sizeof(ack) || ack == 0)
        throw std::runtime_error("Failed to receive ACK for theta velocity command");
    */
}
