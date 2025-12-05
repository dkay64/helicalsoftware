#pragma once

#include <chrono>
#include <cstdint>
#include <string>
#include <vector>

class Esp32UART {
public:
    struct ImuSample {
        uint32_t timestampUs = 0;
        float ax = 0.0f;
        float ay = 0.0f;
        float az = 0.0f;
        float gx = 0.0f;
        float gy = 0.0f;
        float gz = 0.0f;
        float omega = 0.0f;
        float radialAccel = 0.0f;
        float correctiveMass_g = 0.0f;
        float correctiveAngle_deg = 0.0f;
    };

    Esp32UART(const std::string& uartDevice, int baudRate);
    ~Esp32UART();

    void writeCommand(uint8_t command, uint8_t subcommand, uint8_t value);
    int32_t getEncoderPosition(uint8_t encoder);
    void getAllEncoderPositions(int32_t positions[5]);
    void setDcDriverPwm(uint8_t pwm_val);
    void setDcDriverDir(bool dir_val);
    void startThetaZero();
    bool isThetaZeroed();
    int32_t getThetaZeroMeasurement();
    void waitForThetaZeroComplete();
    void setThetaVelocity(int32_t velocity);

    bool getImuSample(ImuSample& outSample, uint32_t timeoutMs = 500);
    bool requestImuCalibration(uint32_t timeoutMs = 5000);

private:
    struct PacketHeader {
        char sync0 = 'I';
        char sync1 = 'M';
        uint8_t type = 0;
        uint8_t length = 0;
    };

    struct SamplePayload {
        uint32_t timestampUs;
        float ax;
        float ay;
        float az;
        float gx;
        float gy;
        float gz;
        float omega;
        float radialAccel;
        float correctiveMass_g;
        float correctiveAngle_deg;
    };

    static constexpr uint8_t CMD_ENCODER_POSITION = 0x10;
    static constexpr uint8_t ENCODER_ALL = 0xFF;
    static constexpr uint8_t CMD_DC_DRIVER = 0x20;
    static constexpr uint8_t DC_SUB_PWM = 0x01;
    static constexpr uint8_t DC_SUB_DIR = 0x02;
    static constexpr uint8_t CMD_THETA_VEL = 0x30;
    static constexpr uint8_t THETA_VEL_SET = 0x01;
    static constexpr uint8_t CMD_THETA_ZERO = 0x40;
    static constexpr uint8_t THETA_ZERO_START = 0x01;
    static constexpr uint8_t THETA_ZERO_STATUS = 0x02;
    static constexpr uint8_t THETA_ZERO_READ = 0x03;

    static constexpr uint8_t CMD_IMU = 0x50;
    static constexpr uint8_t IMU_SUB_GET_SAMPLE = 0x01;
    static constexpr uint8_t IMU_SUB_START_STREAM = 0x02;
    static constexpr uint8_t IMU_SUB_STOP_STREAM = 0x03;
    static constexpr uint8_t IMU_SUB_START_CALIB = 0x04;

    static constexpr uint8_t PACKET_TYPE_ACK = 0xA0;
    static constexpr uint8_t PACKET_TYPE_SAMPLE = 0xA1;
    static constexpr uint8_t PACKET_TYPE_STATUS = 0xA2;

    int uartFd = -1;
    std::string device;
    int baud = 0;
    ImuSample latestImuSample_{};
    bool hasLatestImuSample_ = false;

    bool readBytes(uint8_t* dst, size_t len, std::chrono::steady_clock::time_point deadline);
    bool readPacket(PacketHeader& header, std::vector<uint8_t>& payload, std::chrono::steady_clock::time_point deadline);
    bool parseSamplePayload(const std::vector<uint8_t>& payload, ImuSample& outSample);
    bool waitForImuAck(uint8_t subcommand, std::chrono::steady_clock::time_point deadline);
};
