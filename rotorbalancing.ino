#include <Wire.h>
#include <MPU6050.h>

// ===== Hardware configuration (update to match your carrier) =====
constexpr int IMU_SDA_PIN = 21;          // TODO: replace with actual SDA pin on the Jetson hat
constexpr int IMU_SCL_PIN = 22;          // TODO: replace with actual SCL pin on the Jetson hat
constexpr int ESP32_UART_RX_PIN = 16;    // UART line back to Jetson (ESP32 RX)
constexpr int ESP32_UART_TX_PIN = 17;    // UART line back to Jetson (ESP32 TX)

constexpr uint32_t HOST_BAUD = 115200;
constexpr uint32_t I2C_FREQ_HZ = 400000;

// ===== Physical constants =====
constexpr float TOTAL_ROTOR_MASS_KG = 100.0f;  // Update to measured mass
constexpr float CORRECTION_RADIUS_M = 0.10f;   // 10 cm default
constexpr float MIN_OMEGA_RAD_S = 5.0f;        // Ignore balance math below this spin speed
constexpr float ACC_LSB_TO_MPS2 = 9.80665f / 16384.0f;   // MPU6050 accel conversion @ +/-2 g
constexpr float GYRO_LSB_TO_RAD_S = DEG_TO_RAD / 131.0f; // MPU6050 gyro conversion @ +/-250 deg/s

constexpr uint32_t CONTROL_LOOP_US = 5000;     // 200 Hz control loop
constexpr uint32_t DEFAULT_STREAM_INTERVAL_US = 20000; // 50 Hz streaming by default
constexpr float RADIAL_ALPHA = 0.1f;           // Low-pass smoothing factor for radial acceleration

// ===== Command protocol shared with the Jetson host =====
enum : uint8_t {
  CMD_IMU = 0x50
};

enum : uint8_t {
  IMU_SUB_GET_SAMPLE     = 0x01,
  IMU_SUB_START_STREAM   = 0x02,
  IMU_SUB_STOP_STREAM    = 0x03,
  IMU_SUB_START_CALIB    = 0x04
};

enum : uint8_t {
  PACKET_TYPE_ACK     = 0xA0,
  PACKET_TYPE_SAMPLE  = 0xA1,
  PACKET_TYPE_STATUS  = 0xA2
};

struct Bias {
  float ax = 0.0f;
  float ay = 0.0f;
  float az = 0.0f;
  float gx = 0.0f;
  float gy = 0.0f;
  float gz = 0.0f;
};

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
  float correctiveAngleRad = 0.0f;
};

struct CommandFrame {
  uint8_t command = 0;
  uint8_t subcommand = 0;
  uint8_t value = 0;
  uint8_t data0 = 0;
  uint8_t data1 = 0;
  uint8_t data2 = 0;
};

struct PacketHeader {
  uint8_t sync0 = 'I';
  uint8_t sync1 = 'M';
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

MPU6050 imu;
HardwareSerial& hostSerial = Serial1;

Bias imuBias;
bool biasValid = false;

ImuSample latestSample;
float filteredRadialAccel = 0.0f;
float currentAngle = 0.0f;

uint32_t lastLoopMicros = 0;
uint32_t lastStreamMicros = 0;
uint32_t streamIntervalUs = DEFAULT_STREAM_INTERVAL_US;
bool streamEnabled = false;

// ===== Function declarations =====
void configureImu();
void calibrateImu(uint16_t samples = 2000);
ImuSample readImuSample();
void serviceHostCommands();
void handleCommand(const CommandFrame& frame);
void handleImuCommand(const CommandFrame& frame);
void sendAck(uint8_t subcommand, uint8_t status);
void sendStatus(const char* message);
void sendSamplePacket(const ImuSample& sample);
float wrapAngle(float angleRad);
float computeCorrectiveMass(float radialAccel, float omega);

void setup() {
  Serial.begin(115200);
  hostSerial.begin(HOST_BAUD, SERIAL_8N1, ESP32_UART_RX_PIN, ESP32_UART_TX_PIN);

  Wire.begin(IMU_SDA_PIN, IMU_SCL_PIN);
  Wire.setClock(I2C_FREQ_HZ);

  configureImu();
  calibrateImu();

  lastLoopMicros = micros();
  lastStreamMicros = lastLoopMicros;

  sendStatus("IMU ready");
}

void loop() {
  serviceHostCommands();

  const uint32_t now = micros();
  if (now - lastLoopMicros >= CONTROL_LOOP_US) {
    latestSample = readImuSample();
    lastLoopMicros = now;
  }

  if (streamEnabled && (micros() - lastStreamMicros) >= streamIntervalUs) {
    sendSamplePacket(latestSample);
    lastStreamMicros = micros();
  }
}

void configureImu() {
  imu.initialize();
  imu.setSleepEnabled(false);
  imu.setI2CMasterModeEnabled(false);
  imu.setFullScaleAccelRange(MPU6050_ACCEL_FS_2);
  imu.setFullScaleGyroRange(MPU6050_GYRO_FS_250);

  if (!imu.testConnection()) {
    Serial.println("IMU connection failed!");
    sendStatus("IMU connection failed");
    while (true) {
      delay(1000);
    }
  }
}

void calibrateImu(uint16_t samples) {
  Serial.println("Starting IMU bias calibration...");

  imuBias = {};
  biasValid = false;

  const uint16_t discard = samples / 10;
  uint16_t validSamples = 0;

  for (uint16_t i = 0; i < samples; ++i) {
    int16_t axRaw, ayRaw, azRaw, gxRaw, gyRaw, gzRaw;
    imu.getMotion6(&axRaw, &ayRaw, &azRaw, &gxRaw, &gyRaw, &gzRaw);

    if (i >= discard) {
      imuBias.ax += axRaw * ACC_LSB_TO_MPS2;
      imuBias.ay += ayRaw * ACC_LSB_TO_MPS2;
      imuBias.az += azRaw * ACC_LSB_TO_MPS2 - 9.80665f; // remove gravity component assuming Z-up
      imuBias.gx += gxRaw * GYRO_LSB_TO_RAD_S;
      imuBias.gy += gyRaw * GYRO_LSB_TO_RAD_S;
      imuBias.gz += gzRaw * GYRO_LSB_TO_RAD_S;
      ++validSamples;
    }
    delay(2);
  }

  const float invSamples = (validSamples == 0) ? 0.0f : 1.0f / static_cast<float>(validSamples);
  imuBias.ax *= invSamples;
  imuBias.ay *= invSamples;
  imuBias.az *= invSamples;
  imuBias.gx *= invSamples;
  imuBias.gy *= invSamples;
  imuBias.gz *= invSamples;

  biasValid = true;
  Serial.println("IMU calibration complete.");
  sendAck(IMU_SUB_START_CALIB, 0x01);
}

ImuSample readImuSample() {
  ImuSample sample;
  int16_t axRaw, ayRaw, azRaw, gxRaw, gyRaw, gzRaw;
  imu.getMotion6(&axRaw, &ayRaw, &azRaw, &gxRaw, &gyRaw, &gzRaw);

  const uint32_t now = micros();
  sample.timestampUs = now;

  float ax = axRaw * ACC_LSB_TO_MPS2 - imuBias.ax;
  float ay = ayRaw * ACC_LSB_TO_MPS2 - imuBias.ay;
  float az = azRaw * ACC_LSB_TO_MPS2 - imuBias.az;

  float gx = gxRaw * GYRO_LSB_TO_RAD_S - imuBias.gx;
  float gy = gyRaw * GYRO_LSB_TO_RAD_S - imuBias.gy;
  float gz = gzRaw * GYRO_LSB_TO_RAD_S - imuBias.gz;

  sample.ax = ax;
  sample.ay = ay;
  sample.az = az;
  sample.gx = gx;
  sample.gy = gy;
  sample.gz = gz;

  const float dt = (now - latestSample.timestampUs) / 1e6f;
  currentAngle = wrapAngle(currentAngle + gz * dt);

  float omega = fabsf(gz);
  sample.omega = omega;

  const float radialInstant = sqrtf(ax * ax + ay * ay);
  filteredRadialAccel += RADIAL_ALPHA * (radialInstant - filteredRadialAccel);

  sample.radialAccel = filteredRadialAccel;

  if (omega < MIN_OMEGA_RAD_S) {
    sample.correctiveMass_g = 0.0f;
  } else {
    sample.correctiveMass_g = computeCorrectiveMass(filteredRadialAccel, omega);
  }

  const float imbalanceAngle = atan2f(ay, ax);
  sample.correctiveAngleRad = wrapAngle(imbalanceAngle + PI); // opposite side of imbalance

  return sample;
}

void serviceHostCommands() {
  while (hostSerial.available() >= sizeof(CommandFrame)) {
    CommandFrame frame;
    hostSerial.readBytes(reinterpret_cast<uint8_t*>(&frame), sizeof(frame));
    handleCommand(frame);
  }
}

void handleCommand(const CommandFrame& frame) {
  if (frame.command == CMD_IMU) {
    handleImuCommand(frame);
  } else {
    sendStatus("Unknown command");
  }
}

void handleImuCommand(const CommandFrame& frame) {
  switch (frame.subcommand) {
    case IMU_SUB_GET_SAMPLE:
      sendSamplePacket(latestSample);
      sendAck(frame.subcommand, 0x01);
      break;

    case IMU_SUB_START_STREAM: {
      const uint16_t periodMs = frame.value | (static_cast<uint16_t>(frame.data0) << 8);
      if (periodMs > 0) {
        streamIntervalUs = static_cast<uint32_t>(periodMs) * 1000UL;
      } else {
        streamIntervalUs = DEFAULT_STREAM_INTERVAL_US;
      }
      streamEnabled = true;
      sendAck(frame.subcommand, 0x01);
      break;
    }

    case IMU_SUB_STOP_STREAM:
      streamEnabled = false;
      sendAck(frame.subcommand, 0x01);
      break;

    case IMU_SUB_START_CALIB:
      calibrateImu();
      break;

    default:
      sendAck(frame.subcommand, 0x00);
      break;
  }
}

void sendAck(uint8_t subcommand, uint8_t status) {
  PacketHeader header;
  header.type = PACKET_TYPE_ACK;
  header.length = 3;

  uint8_t payload[3] = { CMD_IMU, subcommand, status };
  hostSerial.write(reinterpret_cast<uint8_t*>(&header), sizeof(header));
  hostSerial.write(payload, sizeof(payload));
}

void sendStatus(const char* message) {
  const uint8_t len = static_cast<uint8_t>(min<size_t>(250, strlen(message)));
  PacketHeader header;
  header.type = PACKET_TYPE_STATUS;
  header.length = len;

  hostSerial.write(reinterpret_cast<uint8_t*>(&header), sizeof(header));
  hostSerial.write(reinterpret_cast<const uint8_t*>(message), len);
}

void sendSamplePacket(const ImuSample& sample) {
  PacketHeader header;
  header.type = PACKET_TYPE_SAMPLE;
  header.length = sizeof(SamplePayload);

  SamplePayload payload {
    sample.timestampUs,
    sample.ax,
    sample.ay,
    sample.az,
    sample.gx,
    sample.gy,
    sample.gz,
    sample.omega,
    sample.radialAccel,
    sample.correctiveMass_g,
    sample.correctiveAngleRad * RAD_TO_DEG
  };

  hostSerial.write(reinterpret_cast<uint8_t*>(&header), sizeof(header));
  hostSerial.write(reinterpret_cast<uint8_t*>(&payload), sizeof(payload));
}

float wrapAngle(float angleRad) {
  while (angleRad > PI) {
    angleRad -= TWO_PI;
  }
  while (angleRad < -PI) {
    angleRad += TWO_PI;
  }
  return angleRad;
}

float computeCorrectiveMass(float radialAccel, float omega) {
  const float omegaSq = omega * omega;
  if (omegaSq < 1e-3f) {
    return 0.0f;
  }
  const float imbalanceForce = TOTAL_ROTOR_MASS_KG * radialAccel;
  const float correctiveMassKg = imbalanceForce / (CORRECTION_RADIUS_M * omegaSq);
  return correctiveMassKg * 1000.0f;
}
