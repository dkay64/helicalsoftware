#include <Wire.h>
#include <MPU6050.h>

MPU6050 imu;
int16_t accX_raw, accY_raw, accZ_raw, gyroX_raw, gyroY_raw, gyroZ_raw;
float accX, accY, accZ, gyroX, gyroY, gyroZ, omega, imuR, Ar;

float angPos = 0;
unsigned long lastTime = 0;
float correctAng = 0;

float m_tot = 100; // Total spinning mass of HeliCAL in kg
float r_correct = 10; // Distance in cm to place mass

void setup() {
  Serial.begin(9600);
  Wire.begin();
  imu.initialize();
  
  if (!imu.testConnection()) {
    Serial.println("IMU connection failed!");
    while (1);
  }
  Serial.println("IMU connected!");
}

void loop() {
  imu.getMotion6(&accX_raw, &accY_raw, &accZ_raw, &gyroX_raw, &gyroY_raw, &gyroZ_raw);
  
  accX = accX_raw / 16384.0;
  accY = accY_raw / 16384.0;
  accZ = accZ_raw / 16384.0;
  
  gyroX = gyroZ_raw / 131.0;
  gyroY = gyroY_raw / 131.0;
  gyroZ = gyroZ_raw / 131.0;
  
  float threshold = 0.1;

  omega=sqrt(sq(gyroX)+sq(gyroY)+sq(gyroZ));
  imuR=sqrt(sq(accX)+sq(accY))/sq(omega)*100;
  Ar=imuR*sq(omega);
  
  float m_correct=estCorrectiveMass(Ar,r_correct,omega,m_tot);

  if (abs(omega)<5){
    m_correct=0;
    omega=0;
  }

  unsigned long currentTime = millis();
  float dt=(currentTime-lastTime)/1000.0;
  lastTime=currentTime;

  angPos+=omega*dt;
  angPos=fmod(angPos, 2*PI);

  static float maxAr=0;
  static float imbalancedAng=0;

  if (Ar>maxAr) {
    maxAr=Ar;
    imbalancedAng=angPos;
  }

  correctAng=imbalancedAng+PI;
  correctAng=fmod(correctAng, 2*PI);

  maxAr=0;
  imbalancedAng=0;

  if (abs(accX) > threshold || abs(accY) > threshold) {
    Serial.print("Imbalance detected!");
  }
  else {
    Serial.print("Rotor is balanced.");
  }
  Serial.print(" Corrective Mass: "); Serial.print(m_correct); Serial.print(" g");
  Serial.print(" Corrective Angle: "); Serial.print(correctAng*180/PI); Serial.print(" deg");
  Serial.print(" r: "); Serial.print(imuR); Serial.print(" cm");
  Serial.print(" aX: "); Serial.print(accX);
  Serial.print(" aY: "); Serial.print(accY);
  Serial.print(" aZ: "); Serial.print(accZ);
  Serial.print(" Ar: "); Serial.print(Ar);
  Serial.print(" omega: "); Serial.println(omega);

  delay(100);
}

float estCorrectiveMass(float Ar,float r_correct,float omega,float m_tot){
  float F_imbalance = m_tot*Ar/100; // Imbalanced force
  float m_correct = F_imbalance/(r_correct/100*sq(omega))*1000; // Corrective mass in grams
  return m_correct;
}
