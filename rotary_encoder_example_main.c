#include "sdkconfig.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "driver/uart.h"
#include "driver/pulse_cnt.h"
#include "driver/gpio.h"
#include "driver/ledc.h"
#include <stdio.h>
#include <string.h>
#include <inttypes.h>
#include <math.h>

//------------------------------------------------------------------------------
// Logging Tag
//------------------------------------------------------------------------------
static const char *TAG = "UART_SLAVE";

//------------------------------------------------------------------------------
// System/Encoder constants (centralized)
//------------------------------------------------------------------------------
// Measured counts per *theta* revolution (post-gearbox). This replaces the
// previously "magic" 245,426 value sprinkled in the host code.
#ifndef COUNTS_PER_THETA_REV
#define COUNTS_PER_THETA_REV 245426
#endif

// Helper conversions
#define RPM_TO_PPS(rpm)  ( (int32_t) llround( ((double)(rpm) * (double)COUNTS_PER_THETA_REV) / 60.0 ) )
#define PPS_TO_RPM(pps)  ( ((double)(pps) * 60.0) / (double)COUNTS_PER_THETA_REV )

// Percent of a full revolution at which we look for the second beam-break during zeroing
#ifndef ZERO_SECOND_FALL_FRACTION
#define ZERO_SECOND_FALL_FRACTION 0.85
#endif

// Glitch filter (nanoseconds)
#ifndef PCNT_GLITCH_NS
#define PCNT_GLITCH_NS 3000
#endif

// DIR polarity: set to 1 if "forward" should drive DIR=1, else 0
#ifndef DC_DIR_FORWARD_LEVEL
#define DC_DIR_FORWARD_LEVEL 1
#endif

//------------------------------------------------------------------------------
// PID state for theta velocity controller (global)
//------------------------------------------------------------------------------
static double pid_integral    = 0.0;
static double pid_prev_error  = 0.0;
static int    pid_last_pwm    = 0;

// Measured velocity (pulses/sec), updated by theta_velocity_task
static volatile int32_t measured_theta_velocity = 0;

//------------------------------------------------------------------------------
// Task Notification Bit for beam-break → zeroing
//------------------------------------------------------------------------------
#define NOTIF_FALL_BIT  (1u << 0)
static int32_t last_break_count = 0;
#define BB_DEBOUNCE_TIME_MS   2000
static TickType_t last_bb_tick = 0;

//------------------------------------------------------------------------------
// Command Definitions (6-byte commands)
//------------------------------------------------------------------------------
// --- Encoder Commands (first byte 0x10) ---
#define CMD_ENCODER_POSITION  0x10
#define ENCODER_ALL           0xFF
// --- DC Driver Commands (first byte 0x20) ---
#define CMD_DC_DRIVER         0x20
#define DC_SUB_PWM            0x01
#define DC_SUB_DIR            0x02
// --- Theta Velocity (PID) Commands (first byte 0x30) ---
#define CMD_THETA_VEL         0x30
#define THETA_VEL_SET         0x01   // payload: int32_le pulses/sec
#define THETA_VEL_GET         0x02   // response: int32_le measured pulses/sec
// --- Theta Zeroing Commands (first byte 0x40) ---
#define CMD_THETA_ZERO        0x40
#define THETA_ZERO_START      0x01
#define THETA_ZERO_STATUS     0x02
#define THETA_ZERO_READ       0x03

//------------------------------------------------------------------------------
// Encoder Definitions
//------------------------------------------------------------------------------
#define PCNT_HIGH_LIMIT  32767
#define PCNT_LOW_LIMIT   -32768

// Encoder pins
#define ENC_1_A GPIO_NUM_9  // TW R A
#define ENC_1_B GPIO_NUM_10 // TW R B
#define ENC_2_A GPIO_NUM_6  // TW T A
#define ENC_2_B GPIO_NUM_7  // TW T B
#define ENC_3_A GPIO_NUM_3  // Theta A
#define ENC_3_B GPIO_NUM_8  // Theta B
#define ENC_4_A GPIO_NUM_1  // CW T A
#define ENC_4_B GPIO_NUM_2  // CW T B
#define ENC_5_A GPIO_NUM_4  // CW R A
#define ENC_5_B GPIO_NUM_5  // CW R B

volatile int32_t total_counts[5] = {0};
pcnt_unit_handle_t pcnt_units[5] = {NULL};

typedef struct {
    pcnt_unit_handle_t unit;
    int                index;
} encoder_data_t;

static bool pcnt_overflow_handler(pcnt_unit_handle_t unit,
                                  const pcnt_watch_event_data_t *edata,
                                  void *user_ctx)
{
    encoder_data_t *e = (encoder_data_t*)user_ctx;
    int idx = e->index;
    int wv  = edata->watch_point_value;
    if (wv == PCNT_HIGH_LIMIT) {
        total_counts[idx] += PCNT_HIGH_LIMIT;
    } else {
        total_counts[idx] -= PCNT_HIGH_LIMIT;
    }
    return false;
}

static void init_encoder(int idx, gpio_num_t a, gpio_num_t b, pcnt_unit_handle_t *unit)
{
    pcnt_unit_config_t ucfg = {
        .high_limit = PCNT_HIGH_LIMIT,
        .low_limit  = PCNT_LOW_LIMIT,
    };
    ESP_ERROR_CHECK(pcnt_new_unit(&ucfg, unit));

    // glitch‐filter
    pcnt_glitch_filter_config_t fcfg = {
        .max_glitch_ns = PCNT_GLITCH_NS,
    };
    ESP_ERROR_CHECK(pcnt_unit_set_glitch_filter(*unit, &fcfg));

    // channel A
    pcnt_chan_config_t cA = {
        .edge_gpio_num  = a,
        .level_gpio_num = b,
    };
    pcnt_channel_handle_t chA;
    ESP_ERROR_CHECK(pcnt_new_channel(*unit, &cA, &chA));

    // channel B
    pcnt_chan_config_t cB = {
        .edge_gpio_num  = b,
        .level_gpio_num = a,
    };
    pcnt_channel_handle_t chB;
    ESP_ERROR_CHECK(pcnt_new_channel(*unit, &cB, &chB));

    ESP_ERROR_CHECK(pcnt_channel_set_edge_action(chA,
                       PCNT_CHANNEL_EDGE_ACTION_DECREASE,
                       PCNT_CHANNEL_EDGE_ACTION_INCREASE));
    ESP_ERROR_CHECK(pcnt_channel_set_level_action(chA,
                       PCNT_CHANNEL_LEVEL_ACTION_KEEP,
                       PCNT_CHANNEL_LEVEL_ACTION_INVERSE));
    ESP_ERROR_CHECK(pcnt_channel_set_edge_action(chB,
                       PCNT_CHANNEL_EDGE_ACTION_INCREASE,
                       PCNT_CHANNEL_EDGE_ACTION_DECREASE));
    ESP_ERROR_CHECK(pcnt_channel_set_level_action(chB,
                       PCNT_CHANNEL_LEVEL_ACTION_KEEP,
                       PCNT_CHANNEL_LEVEL_ACTION_INVERSE));

    int watch_pts[2] = { PCNT_LOW_LIMIT, PCNT_HIGH_LIMIT };
    for (int i = 0; i < 2; ++i) {
        ESP_ERROR_CHECK(pcnt_unit_add_watch_point(*unit, watch_pts[i]));
    }

    static encoder_data_t ed[5];
    ed[idx].unit  = *unit;
    ed[idx].index = idx;
    pcnt_event_callbacks_t cbs = { .on_reach = pcnt_overflow_handler };
    ESP_ERROR_CHECK(pcnt_unit_register_event_callbacks(*unit, &cbs, &ed[idx]));
    ESP_ERROR_CHECK(pcnt_unit_enable(*unit));
    ESP_ERROR_CHECK(pcnt_unit_clear_count(*unit));
    ESP_ERROR_CHECK(pcnt_unit_start(*unit));
}

static void init_encoders(void)
{
    init_encoder(0, ENC_1_A, ENC_1_B, &pcnt_units[0]);
    init_encoder(1, ENC_2_A, ENC_2_B, &pcnt_units[1]);
    init_encoder(2, ENC_3_A, ENC_3_B, &pcnt_units[2]);
    init_encoder(3, ENC_4_A, ENC_4_B, &pcnt_units[3]);
    // ESP32-S2 Only has 4 PCNT counters
    // init_encoder(4, ENC_5_A, ENC_5_B, &pcnt_units[4]);
}

static void update_encoder_positions(int32_t *pos)
{
    for (int i = 0; i < 5; ++i) {
        int cnt = 0;
        if (pcnt_units[i]) {
            ESP_ERROR_CHECK(pcnt_unit_get_count(pcnt_units[i], &cnt));
        }
        pos[i] = total_counts[i] + cnt;
    }
}

//------------------------------------------------------------------------------
// DC Driver
//------------------------------------------------------------------------------
#define DC_PWM_GPIO      GPIO_NUM_13
#define DC_PWM_CHANNEL   LEDC_CHANNEL_0
#define DC_PWM_TIMER     LEDC_TIMER_0
#define DC_PWM_FREQ_HZ   5000
#define DC_PWM_DUTY_RES  LEDC_TIMER_8_BIT
#define DC_DIR_GPIO      GPIO_NUM_12

static inline void dc_apply_pwm_and_dir(int pwm_abs, int dir_forward)
{
    // clamp
    if (pwm_abs < 0) pwm_abs = 0;
    if (pwm_abs > 255) pwm_abs = 255;

    // set direction first to avoid brief reverse torque
    gpio_set_level(DC_DIR_GPIO, dir_forward ? DC_DIR_FORWARD_LEVEL : !DC_DIR_FORWARD_LEVEL);

    ledc_set_duty(LEDC_LOW_SPEED_MODE, DC_PWM_CHANNEL, pwm_abs);
    ledc_update_duty(LEDC_LOW_SPEED_MODE, DC_PWM_CHANNEL);
}

static void init_dc_driver(void)
{
    ledc_timer_config_t tcfg = {
        .speed_mode     = LEDC_LOW_SPEED_MODE,
        .timer_num      = DC_PWM_TIMER,
        .duty_resolution= DC_PWM_DUTY_RES,
        .freq_hz        = DC_PWM_FREQ_HZ,
        .clk_cfg        = LEDC_AUTO_CLK
    };
    ESP_ERROR_CHECK(ledc_timer_config(&tcfg));

    ledc_channel_config_t ccfg = {
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .channel    = DC_PWM_CHANNEL,
        .timer_sel  = DC_PWM_TIMER,
        .intr_type  = LEDC_INTR_DISABLE,
        .gpio_num   = DC_PWM_GPIO,
        .duty       = 0,
        .hpoint     = 0
    };
    ESP_ERROR_CHECK(ledc_channel_config(&ccfg));

    gpio_config_t gcfg = {
        .pin_bit_mask = 1ULL<<DC_DIR_GPIO,
        .mode         = GPIO_MODE_OUTPUT,
        .pull_up_en   = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type    = GPIO_INTR_DISABLE
    };
    ESP_ERROR_CHECK(gpio_config(&gcfg));

    // Example extra lines left as-is (I2C lines used elsewhere)
    gpio_config_t io_conf = {
        .pin_bit_mask = (1ULL<<44) | (1ULL<<43),
        .mode         = GPIO_MODE_INPUT,
        .pull_up_en   = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
    };
    gpio_config(&io_conf);
}

//------------------------------------------------------------------------------
// UART
//------------------------------------------------------------------------------
static void init_uart(void)
{
    uart_config_t ucfg = {
        .baud_rate = 115200,
        .data_bits = UART_DATA_8_BITS,
        .parity    = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE
    };
    ESP_ERROR_CHECK(uart_driver_install(UART_NUM_1, 2048, 0, 0, NULL, 0));
    ESP_ERROR_CHECK(uart_param_config(UART_NUM_1, &ucfg));
    ESP_ERROR_CHECK(uart_set_pin(UART_NUM_1,
                                GPIO_NUM_17,
                                GPIO_NUM_18,
                                UART_PIN_NO_CHANGE,
                                UART_PIN_NO_CHANGE));
}

//------------------------------------------------------------------------------
// Break-Beam for Zeroing
//------------------------------------------------------------------------------
#define BB_PIN GPIO_NUM_11
static TaskHandle_t thetaZeroTaskHandle = NULL;

static void IRAM_ATTR bb_isr_handler(void* arg)
{
    TickType_t tick = xTaskGetTickCountFromISR();
    if (tick - last_bb_tick < pdMS_TO_TICKS(BB_DEBOUNCE_TIME_MS)) {
        return;
    }
    last_bb_tick = tick;

    // If you later re-enable fall notifications, you can notify here
    // BaseType_t woken = pdFALSE;
    // xTaskNotifyFromISR(thetaZeroTaskHandle, NOTIF_FALL_BIT, eSetBits, &woken);
    // if (woken) portYIELD_FROM_ISR();
}

static void init_bb_interrupt(void)
{
    gpio_config_t cf = {
        .intr_type    = GPIO_INTR_NEGEDGE,
        .mode         = GPIO_MODE_INPUT,
        .pin_bit_mask = 1ULL<<BB_PIN,
        .pull_up_en   = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE
    };
    ESP_ERROR_CHECK(gpio_config(&cf));
    ESP_ERROR_CHECK(gpio_install_isr_service(0));
    ESP_ERROR_CHECK(gpio_isr_handler_add(BB_PIN, bb_isr_handler, NULL));
}

//------------------------------------------------------------------------------
// Theta Zeroing Task (0x40)
//------------------------------------------------------------------------------
static volatile int32_t theta_measured_value = 0;

static void theta_zeroing_task(void *arg)
{
    enum { TH_IDLE, TH_FALL1, TH_LOOP, TH_FALL2 } state = TH_IDLE;
    uint32_t notif;
    while (1) {
        xTaskNotifyWait(0, 0xFFFFFFFF, &notif, pdMS_TO_TICKS(10));
        if (notif & NOTIF_FALL_BIT) {
            if (state == TH_FALL1) {
                total_counts[2] = 0;
                ESP_ERROR_CHECK(pcnt_unit_clear_count(pcnt_units[2]));
                state = TH_LOOP;
            } else if (state == TH_FALL2) {
                int cnt = 0;
                ESP_ERROR_CHECK(pcnt_unit_get_count(pcnt_units[2], &cnt));
                theta_measured_value = total_counts[2] + cnt;
                total_counts[2] = 0;
                ESP_ERROR_CHECK(pcnt_unit_clear_count(pcnt_units[2]));
                // reset PID
                pid_integral   = 0.0;
                pid_prev_error = 0.0;
                pid_last_pwm   = 0;
                uint8_t m = 1;
                uart_write_bytes(UART_NUM_1, (char*)&m, 1);
                uart_wait_tx_done(UART_NUM_1, pdMS_TO_TICKS(100));
                state = TH_IDLE;
            }
        }
        if (state == TH_LOOP) {
            int cnt = 0;
            ESP_ERROR_CHECK(pcnt_unit_get_count(pcnt_units[2], &cnt));
            // wait until we have ~85% of a revolution before arming for the second fall
            if (total_counts[2] + cnt > (int32_t)(ZERO_SECOND_FALL_FRACTION * (double)COUNTS_PER_THETA_REV)) {
                state = TH_FALL2;
            }
        }
        vTaskDelay(pdMS_TO_TICKS(10));
    }
}

//------------------------------------------------------------------------------
// Theta Velocity Task (PID, 0x30) - signed control with DIR
//------------------------------------------------------------------------------
static volatile int32_t desired_theta_velocity = 0; // pulses/sec (signed)
static volatile bool    pid_enabled           = false;

static void theta_velocity_task(void *arg)
{
    int prev_enc = 0, cur_enc = 0;
    const double dt = 0.02; // 50 Hz
    // Start with conservative gains; tune as needed
    double kp = 0.06, ki = 0.005, kd = 0.0;

    // prime prev_enc
    ESP_ERROR_CHECK(pcnt_unit_get_count(pcnt_units[2], &prev_enc));
    prev_enc += total_counts[2];

    while (1) {
        vTaskDelay(pdMS_TO_TICKS((int)(dt * 1000.0)));

        // maintain baseline when disabled
        if (!pid_enabled) {
            ESP_ERROR_CHECK(pcnt_unit_get_count(pcnt_units[2], &cur_enc));
            prev_enc = cur_enc + total_counts[2];
            // also force PWM=0 when disabled
            dc_apply_pwm_and_dir(0, /*forward=*/1);
            measured_theta_velocity = 0;
            continue;
        }

        // 1) read encoder, compute signed measured pps
        ESP_ERROR_CHECK(pcnt_unit_get_count(pcnt_units[2], &cur_enc));
        cur_enc += total_counts[2];
        int32_t delta = cur_enc - prev_enc;    // signed by quadrature
        prev_enc = cur_enc;
        double measured = delta / dt;          // pulses/sec (signed)
        measured_theta_velocity = (int32_t) llround(measured);

        // 2) PID on signed velocity
        double err   = (double)desired_theta_velocity - measured;
        pid_integral += err * dt;
        double deriv = (err - pid_prev_error) / dt;
        pid_prev_error = err;

        double u = kp*err + ki*pid_integral + kd*deriv;

        // 3) Output mapping: direction from sign(u), magnitude to PWM with slew limit
        int dir_forward = (u >= 0.0) ? 1 : 0;
        double mag = fabs(u);

        // Saturate magnitude
        if (mag > 255.0) mag = 255.0;

        // Slew-rate limit on PWM steps
        int target_pwm = (int)mag;
        int step = target_pwm - pid_last_pwm;
        const int max_step = 5;
        if      (step >  max_step) target_pwm = pid_last_pwm + max_step;
        else if (step < -max_step) target_pwm = pid_last_pwm - max_step;
        pid_last_pwm = target_pwm;

        // 4) Apply to hardware
        dc_apply_pwm_and_dir(pid_last_pwm, dir_forward);

        // Optional debug
        /*
        ESP_LOGI(TAG,
            "vel: des=%" PRId32 " meas=%" PRId32 " pps (%.3f rpm) err=%.1f pwm=%d dir=%d",
            desired_theta_velocity,
            measured_theta_velocity,
            PPS_TO_RPM(measured_theta_velocity),
            err, pid_last_pwm, dir_forward);
        */
    }
}

//------------------------------------------------------------------------------
// UART Slave Task
//------------------------------------------------------------------------------
static void uart_slave_task(void *arg)
{
    uint8_t cmd[6];
    while (1) {
        int len = uart_read_bytes(UART_NUM_1, cmd, 6, pdMS_TO_TICKS(100));
        if (len == 6) {
            ESP_LOGI(TAG, "UART received: 0x%02X 0x%02X 0x%02X 0x%02X 0x%02X 0x%02X",
                     cmd[0], cmd[1], cmd[2], cmd[3], cmd[4], cmd[5]);

            switch (cmd[0]) {
                case CMD_ENCODER_POSITION: {
                    if (cmd[1] == ENCODER_ALL) {
                        int32_t p[5];
                        update_encoder_positions(p);
                        uart_write_bytes(UART_NUM_1, (char*)p, sizeof(p));
                    } else if (cmd[1] < 4) { // ESP32-S2 only has 4 PCNT counters
                        int cnt = 0;
                        ESP_ERROR_CHECK(pcnt_unit_get_count(pcnt_units[cmd[1]], &cnt));
                        int32_t v = total_counts[cmd[1]] + cnt;
                        uart_write_bytes(UART_NUM_1, (char*)&v, sizeof(v));
                    }
                    uart_wait_tx_done(UART_NUM_1, pdMS_TO_TICKS(100));
                    break;
                }

                case CMD_DC_DRIVER:
                    // Manual DC control disables PID
                    pid_integral = 0.0;
                    pid_prev_error = 0.0;
                    pid_last_pwm = 0;
                    pid_enabled = false;
                    if (cmd[1] == DC_SUB_PWM) {
                        // direct PWM (no sign) keeps last DIR
                        ledc_set_duty(LEDC_LOW_SPEED_MODE, DC_PWM_CHANNEL, cmd[2]);
                        ledc_update_duty(LEDC_LOW_SPEED_MODE, DC_PWM_CHANNEL);
                    } else {
                        // set DIR explicitly
                        gpio_set_level(DC_DIR_GPIO, cmd[2] ? DC_DIR_FORWARD_LEVEL : !DC_DIR_FORWARD_LEVEL);
                    }
                    break;

                case CMD_THETA_VEL:
                    if (cmd[1] == THETA_VEL_SET) {
                        // reset PID state
                        pid_integral   = 0.0;
                        pid_prev_error = 0.0;
                        pid_last_pwm   = 0;

                        // ack (1 byte)
                        uint8_t a = 1;
                        uart_write_bytes(UART_NUM_1, (char*)&a, 1);
                        uart_wait_tx_done(UART_NUM_1, pdMS_TO_TICKS(100));

                        // parse little-endian signed pulses/sec
                        int32_t v = (int32_t)cmd[2]
                                  | ((int32_t)cmd[3] << 8)
                                  | ((int32_t)cmd[4] << 16)
                                  | ((int32_t)cmd[5] << 24);
                        desired_theta_velocity = v;

                        if (v == 0) {
                            pid_enabled = false;
                            dc_apply_pwm_and_dir(0, /*forward=*/1);
                        } else {
                            pid_enabled = true;
                        }
                    } else if (cmd[1] == THETA_VEL_GET) {
                        // respond with measured pulses/sec (int32)
                        uart_write_bytes(UART_NUM_1, (char*)&measured_theta_velocity, sizeof(measured_theta_velocity));
                        uart_wait_tx_done(UART_NUM_1, pdMS_TO_TICKS(100));
                    }
                    break;

                case CMD_THETA_ZERO:
                    if (cmd[1] == THETA_ZERO_START) {
                        // Kick into ~10 rpm using the helper
                        pid_integral   = 0.0;
                        pid_prev_error = 0.0;
                        pid_last_pwm   = 0;
                        desired_theta_velocity = RPM_TO_PPS(10.0);
                        pid_enabled = true;
                        xTaskNotify(thetaZeroTaskHandle, NOTIF_FALL_BIT, eSetBits);
                    } else if (cmd[1] == THETA_ZERO_STATUS) {
                        uint8_t s = theta_measured_value ? 1 : 0;
                        uart_write_bytes(UART_NUM_1, (char*)&s, 1);
                        uart_wait_tx_done(UART_NUM_1, pdMS_TO_TICKS(100));
                    } else if (cmd[1] == THETA_ZERO_READ) {
                        uart_write_bytes(UART_NUM_1, (char*)&theta_measured_value, sizeof(theta_measured_value));
                        uart_wait_tx_done(UART_NUM_1, pdMS_TO_TICKS(100));
                    }
                    break;

                default:
                    ESP_LOGW(TAG, "Unknown command 0x%02X", cmd[0]);
                    break;
            }
        }
        vTaskDelay(pdMS_TO_TICKS(10));
    }
}

//------------------------------------------------------------------------------
// Encoder-Dump Task (optional debug)
//------------------------------------------------------------------------------
static void encoder_dump_task(void *arg)
{
    int32_t p[5];
    while (1) {
        update_encoder_positions(p);
        ESP_LOGI(TAG, "Enc:[%ld,%ld,%ld,%ld,%ld] meas=%" PRId32 "pps (%.3f rpm)",
                 p[0],p[1],p[2],p[3],p[4],
                 measured_theta_velocity,
                 PPS_TO_RPM(measured_theta_velocity));
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}

//------------------------------------------------------------------------------
// app_main
//------------------------------------------------------------------------------
void app_main(void)
{
    ESP_LOGI(TAG,"Initializing system");
    init_uart();
    init_dc_driver();
    init_encoders();
    init_bb_interrupt();

    xTaskCreate(uart_slave_task,     "uart_slave",    4096, NULL,  9, NULL);
    xTaskCreate(theta_zeroing_task,  "theta_zero",    2048, NULL,  9, &thetaZeroTaskHandle);
    xTaskCreate(theta_velocity_task, "theta_velocity",2048, NULL, 10, NULL);
    // xTaskCreate(encoder_dump_task,   "encoder_dump",  2048, NULL,  5, NULL);
}
