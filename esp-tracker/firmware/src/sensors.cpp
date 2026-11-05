#include "sensors.h"

#include <Arduino.h>
#include <Wire.h>

#include <initializer_list>

namespace {

const uint32_t FAST_PERIOD_MS = 50;  // accel + compass
const uint32_t BARO_PERIOD_MS = 500; // one complete pressure reading
const uint8_t BMP180_OSS = 3;        // ultra high resolution, 25.5 ms conversion

bool probe(uint8_t addr)
{
    Wire.beginTransmission(addr);
    return Wire.endTransmission() == 0;
}

bool writeReg(uint8_t addr, uint8_t reg, uint8_t val)
{
    Wire.beginTransmission(addr);
    Wire.write(reg);
    Wire.write(val);
    return Wire.endTransmission() == 0;
}

bool readRegs(uint8_t addr, uint8_t reg, uint8_t *buf, uint8_t n)
{
    Wire.beginTransmission(addr);
    Wire.write(reg);
    if (Wire.endTransmission(false) != 0) return false;
    if (Wire.requestFrom(addr, n) != n) return false;
    for (uint8_t i = 0; i < n; ++i) buf[i] = (uint8_t)Wire.read();
    return true;
}

int readReg(uint8_t addr, uint8_t reg)
{
    uint8_t v;
    return readRegs(addr, reg, &v, 1) ? v : -1;
}

inline int16_t be16(const uint8_t *p) { return (int16_t)((p[0] << 8) | p[1]); }
inline int16_t le16(const uint8_t *p) { return (int16_t)((p[1] << 8) | p[0]); }

} // namespace

bool Sensors::begin(int sda, int scl)
{
    if (sda < 0 || scl < 0) return false;
    Wire.begin(sda, scl);
    Wire.setClock(400000);
    detect();
    return hasAccel() || hasMag() || hasBaro();
}

void Sensors::detect()
{
    // --- accelerometer ---
    for (uint8_t a : {(uint8_t)0x68, (uint8_t)0x69}) {
        if (!probe(a)) continue;
        int who = readReg(a, 0x75);
        if (who == 0x68 || who == 0x70 || who == 0x71 || who == 0x73) {
            imu_ = IMU_MPU;
            imuAddr_ = a;
            imuName_ = who == 0x68 ? "MPU6050" : who == 0x70 ? "MPU6500" : "MPU9250";
            writeReg(a, 0x6B, 0x00); // wake up, internal clock
            delay(5);
            writeReg(a, 0x1C, 0x00); // accel +-2 g
            writeReg(a, 0x1A, 0x04); // DLPF ~20 Hz
            writeReg(a, 0x6A, 0x00); // I2C master off...
            writeReg(a, 0x37, 0x02); // ...and bypass on: the compass behind it (GY-87, MPU9250) shows up
            delay(10);
            break;
        }
    }
    if (imu_ == IMU_NONE && probe(0x53) && readReg(0x53, 0x00) == 0xE5) {
        imu_ = IMU_ADXL345;
        imuAddr_ = 0x53;
        imuName_ = "ADXL345";
        writeReg(0x53, 0x31, 0x08); // full resolution, +-2 g
        writeReg(0x53, 0x2C, 0x09); // 50 Hz
        writeReg(0x53, 0x2D, 0x08); // measure
    }

    // --- magnetometer ---
    if (probe(0x1E)) {
        uint8_t id[3];
        if (readRegs(0x1E, 0x0A, id, 3) && id[0] == 'H' && id[1] == '4' && id[2] == '3') {
            mag_ = MAG_HMC5883L;
            magName_ = "HMC5883L";
            writeReg(0x1E, 0x00, 0x70); // 8 samples averaged, 15 Hz
            writeReg(0x1E, 0x01, 0x20); // +-1.3 Ga
            writeReg(0x1E, 0x02, 0x00); // continuous
        }
    }
    if (mag_ == MAG_NONE && probe(0x0D) && readReg(0x0D, 0x0D) == 0xFF) {
        mag_ = MAG_QMC5883L;
        magName_ = "QMC5883L";
        writeReg(0x0D, 0x0B, 0x01); // set/reset period
        writeReg(0x0D, 0x09, 0x1D); // continuous, 200 Hz, 8 G, OSR 512
    }
    if (mag_ == MAG_NONE && probe(0x0C) && readReg(0x0C, 0x00) == 0x48) {
        mag_ = MAG_AK8963;
        magName_ = "AK8963";
        writeReg(0x0C, 0x0A, 0x00); // power down before changing mode
        delay(10);
        writeReg(0x0C, 0x0A, 0x16); // 16 bit, continuous mode 2 (100 Hz)
    }

    // --- barometer ---
    for (uint8_t a : {(uint8_t)0x77, (uint8_t)0x76}) {
        if (!probe(a)) continue;
        int id = readReg(a, 0xD0);
        if (id == 0x55) {
            uint8_t raw[22];
            if (readRegs(a, 0xAA, raw, 22)) {
                bmp180_parse_cal(raw, &cal180_);
                baro_ = BARO_BMP180;
                baroAddr_ = a;
                baroName_ = "BMP180";
                break;
            }
        } else if (id == 0x58 || id == 0x60) {
            uint8_t raw[24];
            if (readRegs(a, 0x88, raw, 24)) {
                bmp280_parse_cal(raw, &cal280_);
                baro_ = BARO_BMP280;
                baroAddr_ = a;
                baroName_ = id == 0x58 ? "BMP280" : "BME280";
                writeReg(a, 0xF5, 0x10); // standby 0.5 ms, IIR filter x16
                writeReg(a, 0xF4, 0x57); // temp x2, pressure x16, normal mode
                break;
            }
        }
    }
}

void Sensors::readImu()
{
    uint8_t b[6];
    if (imu_ == IMU_MPU && readRegs(imuAddr_, 0x3B, b, 6)) {
        accel_ = {(float)be16(b), (float)be16(b + 2), (float)be16(b + 4)};
        accelOk_ = true;
    } else if (imu_ == IMU_ADXL345 && readRegs(imuAddr_, 0x32, b, 6)) {
        accel_ = {(float)le16(b), (float)le16(b + 2), (float)le16(b + 4)};
        accelOk_ = true;
    } else {
        accelOk_ = false;
    }
}

void Sensors::readMag()
{
    uint8_t b[7];
    bool ok = false;
    switch (mag_) {
    case MAG_HMC5883L:
        // register order is X, Z, Y; -4096 means overflow
        if (readRegs(0x1E, 0x03, b, 6)) {
            int16_t x = be16(b), z = be16(b + 2), y = be16(b + 4);
            if (x != -4096 && y != -4096 && z != -4096) {
                mag_v_ = {(float)x, (float)y, (float)z};
                ok = true;
            }
        }
        break;
    case MAG_QMC5883L: {
        int st = readReg(0x0D, 0x06);
        if (st >= 0 && (st & 0x01) && readRegs(0x0D, 0x00, b, 6)) {
            mag_v_ = {(float)le16(b), (float)le16(b + 2), (float)le16(b + 4)};
            ok = true;
        } else if (st >= 0) {
            return; // no new data yet: keep the previous sample, not an error
        }
        break;
    }
    case MAG_AK8963: {
        int st1 = readReg(0x0C, 0x02);
        if (st1 >= 0 && (st1 & 0x01) && readRegs(0x0C, 0x03, b, 7)) { // reading ST2 (7th byte) releases the data
            if (!(b[6] & 0x08)) {                                      // HOFL: magnetic overflow
                // AK8963 axes are X<->Y swapped and Z inverted relative to the MPU9250 accelerometer
                mag_v_ = {(float)le16(b + 2), (float)le16(b), (float)-le16(b + 4)};
                ok = true;
            }
        } else if (st1 >= 0) {
            return;
        }
        break;
    }
    default:
        return;
    }
    magOk_ = ok;
    if (ok) ++magSeq_;
}

void Sensors::pollBaro(uint32_t now)
{
    if (baro_ == BARO_BMP280) {
        if (now - baroMs_ < BARO_PERIOD_MS) return;
        baroMs_ = now;
        uint8_t b[6];
        if (!readRegs(baroAddr_, 0xF7, b, 6)) {
            pressOk_ = false;
            return;
        }
        int32_t adcP = ((int32_t)b[0] << 12) | ((int32_t)b[1] << 4) | (b[2] >> 4);
        int32_t adcT = ((int32_t)b[3] << 12) | ((int32_t)b[4] << 4) | (b[5] >> 4);
        pressOk_ = bmp280_compensate(cal280_, adcT, adcP, &tempC_, &pressPa_);
        return;
    }
    if (baro_ != BARO_BMP180) return;
    // BMP180: start temperature, read it 5 ms later, start pressure, read it 26 ms later. No delay().
    uint8_t b[3];
    switch (baroPhase_) {
    case 0:
        if (now - baroMs_ < BARO_PERIOD_MS) return;
        baroMs_ = now;
        if (writeReg(baroAddr_, 0xF4, 0x2E)) baroPhase_ = 1;
        else pressOk_ = false;
        break;
    case 1:
        if (now - baroMs_ < 5) return;
        if (!readRegs(baroAddr_, 0xF6, b, 2)) {
            baroPhase_ = 0;
            pressOk_ = false;
            return;
        }
        bmpUt_ = (b[0] << 8) | b[1];
        writeReg(baroAddr_, 0xF4, 0x34 | (BMP180_OSS << 6));
        baroMs_ = now;
        baroPhase_ = 2;
        break;
    case 2:
        if (now - baroMs_ < 27) return;
        baroPhase_ = 0;
        baroMs_ = now;
        if (!readRegs(baroAddr_, 0xF6, b, 3)) {
            pressOk_ = false;
            return;
        }
        {
            int32_t up = (((int32_t)b[0] << 16) | ((int32_t)b[1] << 8) | b[2]) >> (8 - BMP180_OSS);
            bmp180_compensate(cal180_, bmpUt_, up, BMP180_OSS, &tempC_, &pressPa_);
            pressOk_ = pressPa_ > 30000 && pressPa_ < 110000;
        }
        break;
    }
}

void Sensors::poll(uint32_t now)
{
    if (now - lastFastMs_ >= FAST_PERIOD_MS) {
        lastFastMs_ = now;
        if (hasAccel()) readImu();
        if (hasMag()) readMag();
    }
    if (hasBaro()) pollBaro(now);
}
