#include "LED.h"
#include <stdio.h>
#include <string.h>
#include <unistd.h>

LED::LED(uint16_t vid, uint16_t pid) : vendor_id(vid), product_id(pid), hid_handle(nullptr) {
    if (hid_init()) {
        printf("Failed to initialize HIDAPI\n");
    } else {
        hid_handle = hid_open(vendor_id, product_id, NULL);
        if (!hid_handle) {
            printf("Unable to open device\n");
            hid_exit();
        }
    }
}

LED::~LED() {
    if (hid_handle) {
        hid_close(hid_handle);
    }
    hid_exit();
}

bool LED::configure(int current_mA) {
    // Ensure the LED is turned on
    if (!start()) {
        printf("Failed to start LED\n");
        return false;
    }

    // Set the current, default is 450 mA if not provided
    if (!current(current_mA)) {
        printf("Failed to set LED current to %d mA\n", current_mA);
        return false;
    }

    printf("LED configured with current: %d mA\n", current_mA);
    return true;
}

bool LED::start() {
    uint8_t buf[65] = {0};
    buf[0] = 0x00;
    buf[1] = 0x00;
    buf[2] = 0x01;
    buf[3] = 0x03;
    buf[4] = 0x00;
    buf[5] = 0x01;
    buf[6] = 0x1A;
    buf[7] = 0xFF;  // LED ON

    printf("LED ON\n");
    return writeCommand(buf, sizeof(buf));
}

bool LED::stop() {
    uint8_t buf[65] = {0};
    buf[0] = 0x00;
    buf[1] = 0x00;
    buf[2] = 0x01;
    buf[3] = 0x03;
    buf[4] = 0x00;
    buf[5] = 0x01;
    buf[6] = 0x1A;
    buf[7] = 0x00;  // LED OFF

    printf("LED OFF\n");
    return writeCommand(buf, sizeof(buf));
}

bool LED::PWM(int pwm_value) {
    if (pwm_value < 0 || pwm_value > 255) {
        printf("Invalid PWM value. Must be between 0 and 255.\n");
        return false;
    }

    uint8_t buf[65] = {0};
    buf[0] = 0x00;
    buf[1] = 0x00;
    buf[2] = 0x01;
    buf[3] = 0x03;
    buf[4] = 0x00;
    buf[5] = 0x01;
    buf[6] = 0x1A;
    buf[7] = static_cast<uint8_t>(pwm_value);  // Set PWM value

    //printf("Buffer contents: ");
    //for (int i = 0; i < sizeof(buf); i++) {
        //printf("%02X ", buf[i]);
    //}
    //printf("\n");

    printf("Setting LED PWM to %d \n", pwm_value);
    return writeCommand(buf, sizeof(buf));
}

bool LED::current(int current) {
    if (current < 0 || current > 30000) {
        printf("Invalid current value. Must be between 0 and 30000 mA.\n");
        return false;
    }

    uint8_t buf[65] = {0};
    buf[0] = 0x00;
    buf[1] = 0x00;
    buf[2] = 0x01;
    buf[3] = 0x04;
    buf[4] = 0x00;
    buf[5] = 0x02;
    buf[6] = 0x1A;
    
    // Split the current value into high and low bytes
    buf[7] = (current >> 8) & 0xFF;  // LED Current High Byte
    buf[8] = current & 0xFF;         // LED Current Low Byte

    //printf("Buffer contents: ");
    //for (int i = 0; i < sizeof(buf); i++) {
        //printf("%02X ", buf[i]);
    //}
    //printf("\n");

    printf("Setting LED current to %d mA\n", current);
    return writeCommand(buf, sizeof(buf));
}

bool LED::status() {
    uint8_t buf[65] = {0};
    buf[0] = 0x00;
    buf[1] = 0xC0;
    buf[2] = 0x11;
    buf[3] = 0x03;
    buf[4] = 0x00;
    buf[5] = 0x01;
    buf[6] = 0x10;

    printf("Checking hardware status\n");
    if (!writeCommand(buf, sizeof(buf))) {
        return false;
    }

    int res = hid_read(hid_handle, buf, sizeof(buf));
    if (res < 0) {
        printf("Error reading from device\n");
        return false;
    } else {
        printf("Hardware Status:\n");
        printf("  Status Byte 6: %02X\n", buf[6]);
        for (int i = 7; i >= 0; i--) {
            printf("%d", (buf[6] >> i) & 1);
        }
        printf("\n");
    }
    return true;
}

bool LED::temp() {
    uint8_t buf[65] = {0};
    buf[0] = 0x00;
    buf[1] = 0xC0;
    buf[2] = 0x11;
    buf[3] = 0x03;
    buf[4] = 0x00;
    buf[5] = 0x01;
    buf[6] = 0x1C;

    printf("Checking hardware status\n");
    if (!writeCommand(buf, sizeof(buf))) {
        return false;
    }

    int res = hid_read(hid_handle, buf, sizeof(buf));
    if (res < 0) {
        printf("Error reading from device\n");
        return false;
    } else {
        
        uint16_t LED_Driver_Board_Temp_Raw = (buf[6] << 8) | buf[7];
        float LED_Driver_Board_Temp = LED_Driver_Board_Temp_Raw / 10.0;
        uint16_t DMD_Temp_Raw = (buf[8] << 8) | buf[9];
        float DMD_Temp = DMD_Temp_Raw / 10.0;
        uint16_t LED_Temp_Raw = (buf[10] << 8) | buf[11];
        float LED_Temp = LED_Temp_Raw / 10.0;
        
        printf("Hardware Temps:\n");
        printf("    LED Driver Temp (C): %.2f \n", LED_Driver_Board_Temp);
        printf("    DMD Temp (C): %.2f \n", DMD_Temp);
        printf("    LED Temp (C): %.2f \n", LED_Temp);
    }
    return true;
}

bool LED::writeCommand(uint8_t *buf, size_t length) {
    if (hid_write(hid_handle, buf, length) == -1) {
        printf("Failed to write to device\n");
        return false;
    }
    return true;
}
