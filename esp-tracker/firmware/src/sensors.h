// Optional I2C sensors on the tracker: accelerometer (level / tilt compensation), magnetometer
// (compass, to find north) and barometer. Everything is auto-detected at boot; missing parts are
// simply reported as absent. The maths lives in lib/tracker_core (compass.*, baro_calc.*).
//
// Detected chips (common "10DOF" / "9DOF" boards: GY-87, GY-91, GY-80, GY-271, BN-880 compass):
//   accelerometer : MPU6050 / MPU6500 / MPU9250 (0x68/0x69), ADXL345 (0x53)
//   magnetometer  : HMC5883L (0x1E), QMC5883L (0x0D), AK8963 inside an MPU9250 (0x0C, via bypass)
//   barometer     : BMP085/BMP180 (0x77), BMP280/BME280 (0x76/0x77)
#pragma once
#include <stdint.h>

#include "baro_calc.h"
#include "compass.h"

class Sensors {
public:
    // Returns true if at least one sensor answered.
    bool begin(int sda, int scl);
    // Non-blocking; call every loop. Accel/compass at ~20 Hz, baro at ~2 Hz.
    void poll(uint32_t now_ms);

    const char *imuName() const { return imuName_; }
    const char *magName() const { return magName_; }
    const char *baroName() const { return baroName_; }
    bool hasAccel() const { return imu_ != IMU_NONE; }
    bool hasMag() const { return mag_ != MAG_NONE; }
    bool hasBaro() const { return baro_ != BARO_NONE; }

    // latest samples (raw sensor units: only directions / ratios are used)
    bool accelValid() const { return accelOk_; }
    const Vec3 &accel() const { return accel_; }
    bool magValid() const { return magOk_; }
    const Vec3 &mag() const { return mag_v_; }
    uint32_t magSeq() const { return magSeq_; } // increments with every new compass sample
    bool pressValid() const { return pressOk_; }
    float pressPa() const { return pressPa_; }
    float tempC() const { return tempC_; }

private:
    enum Imu : uint8_t { IMU_NONE, IMU_MPU, IMU_ADXL345 };
    enum Mag : uint8_t { MAG_NONE, MAG_HMC5883L, MAG_QMC5883L, MAG_AK8963 };
    enum Baro : uint8_t { BARO_NONE, BARO_BMP180, BARO_BMP280 };

    void detect();
    void readImu();
    void readMag();
    void pollBaro(uint32_t now_ms);

    Imu imu_ = IMU_NONE;
    Mag mag_ = MAG_NONE;
    Baro baro_ = BARO_NONE;
    uint8_t imuAddr_ = 0, baroAddr_ = 0;
    const char *imuName_ = "";
    const char *magName_ = "";
    const char *baroName_ = "";

    Vec3 accel_ = {0, 0, 0}, mag_v_ = {0, 0, 0};
    bool accelOk_ = false, magOk_ = false, pressOk_ = false;
    uint32_t magSeq_ = 0;
    float pressPa_ = 0, tempC_ = 0;

    uint32_t lastFastMs_ = 0;
    // baro state machine
    uint8_t baroPhase_ = 0;
    uint32_t baroMs_ = 0;
    int32_t bmpUt_ = 0;
    Bmp180Cal cal180_ = {};
    Bmp280Cal cal280_ = {};
    uint8_t failCount_ = 0;
};
