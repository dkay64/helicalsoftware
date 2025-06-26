#include "DLPC900.h"
#include <iostream>
#include <string>
#include <vector>
#include <chrono>
#include <thread>

DLPC900::DLPC900()
{
    using namespace std;

    /* Initialize USB HID library */
    hid_init();

    /* Get a linked list of all connected USB HID devices for DLPC900 */
    hid_device_info* devices_linkedList = hid_enumerate(0x451, 0xC900);
    vector<hid_device_info*> devices_list;
    hid_device_info* n = devices_linkedList;
    while (NULL != n)
    {
        devices_list.push_back(n);
        if (0 == n->interface_number)
        {
            handle = hid_open_path(n->path);
        }
        n = n->next;
    }

    /* In case connection couldn't be established */
    if (NULL == handle) {
        cout << "Unable to open connection to DLPC900... \nQuitting..." << endl;
    }
    else
    {
        cout << "Connected to DLPC900..." << "\n" << endl;
    }
}

DLPC900::~DLPC900()
{
    using namespace std;
    hid_close(handle);
    hid_exit();
    cout << "Disconnected from DLPC900..." << "\n" << endl;
}

void DLPC900::configure() {
	using namespace std;
	
    cout << "Configuring DLPC900..." << endl;
    cout << "=========================================================\n" << endl;

    // Set display mode to video
    setDisplayMode(DLPC900_DISPMODE_VIDEO);

    // Set the video source to DisplayPort (DP)
    setVideoSource(DLPC900_IT6535MODE_DP);

    // Set the clock source to FIREBIRD
    setClockSource(DLPC900_CLKSRC_FIREBIRD);

    // Wait for video signal locking
    waitForLocking();

    // Stop any running pattern sequence
    startStopPattern(DLPC900_PATTERN_STOP);

    // Set display mode to Video + Pattern mode
    setDisplayMode(DLPC900_DISPMODE_VIDEOPATT);

    // Set pattern to full white
    setPattern_FullWhite();

    // Configure the pattern LUT for full white
    configPattern_FullWhite();

    // Start the pattern sequence
    startStopPattern(DLPC900_PATTERN_START);

    cout << "=========================================================\n" << endl;
}

uint8_t DLPC900::getMainStatus()
{
    using namespace std;
    uint8_t mainStatus = 0;
    if (NULL != handle)
    {
        unsigned char command[65];
        unsigned char answer[65];
        sendCommand(DLPC900_CMD_READ, DLPC900_CMD_MAINSTATUS, command, 0,
                    answer);
        mainStatus = answer[0];
    }

    return mainStatus;
}

uint8_t DLPC900::getLocking()
{
    uint8_t answer;
    answer = (this->getMainStatus() & 0b00001000) >> 3;
    return answer;
}

uint8_t DLPC900::isDMDok()
{
    using namespace std;
    uint8_t DLPok = 0;
    if (NULL != handle)
    {
        unsigned char command[65];
        unsigned char answer[65];
        sendCommand(DLPC900_CMD_READ, DLPC900_CMD_HWSTATUS, command, 0,
                    answer);

        /* Check answer for Firebird */
        if (0b00010001 == answer[0])
        {
            DLPok = 1;
        }
    }

    return DLPok;
}

int8_t DLPC900::sendCommand(DLPC900_readWrite readWrite, uint16_t command,
                            uint8_t data_in[], uint8_t dataSizeIn, uint8_t data_out[])
{
    using namespace std;

    unsigned char buf_in[65];
    unsigned char buf_out[65];
    buf_in[0] = 0x00;
    if (DLPC900_CMD_READ == readWrite)
    {
        buf_in[1] = 0xC0;
    }
    else if (DLPC900_CMD_WRITE == readWrite)
    {
        buf_in[1] = 0x40;
    }
    else
    {
        return -1;
    }

    buf_in[2] = 0xFF;
    buf_in[3] = dataSizeIn + 2;
    buf_in[4] = 0x00;

    buf_in[5] = command & 0x00FF;
    buf_in[6] = (command & 0xFF00) >> 8;

    for (uint8_t i = 0; i < dataSizeIn; i++)
    {
        buf_in[7 + i] = data_in[i];
    }

    hid_write(handle, buf_in, 64);
    hid_read(handle, buf_out, 64);
    data_out[0] = buf_out[4];

    usleep(200000);

    return 0;
}

void DLPC900::setDisplayMode(uint8_t dispMode)
{
    using namespace std;
    if (NULL != handle)
    {
        unsigned char command;
        command = dispMode;
        unsigned char answer[65];
        cout << "Setting display mode to " << (int)(dispMode) << endl;
        sendCommand(DLPC900_CMD_WRITE, DLPC900_CMD_DISPMODE, &command, 1, answer);
    }
}

void DLPC900::setVideoSource(uint8_t source)
{
    using namespace std;
    if (NULL != handle)
    {
        unsigned char command;
        command = source;
        unsigned char answer[65];
        cout << "Setting video source" << endl;
        sendCommand(DLPC900_CMD_WRITE, DLPC900_CMD_IT6535_MODE, &command,
                    1, answer);
    }
}

void DLPC900::setClockSource(uint8_t source)
{
    using namespace std;
    if (NULL != handle)
    {
        unsigned char command;
        command = source;
        unsigned char answer[65];
        cout << "Setting clock source" << endl;
        sendCommand(DLPC900_CMD_WRITE, DLPC900_CMD_CLKSEL, &command, 1,
                    answer);
    }
}

void DLPC900::startStopPattern(uint8_t startStop)
{
    using namespace std;
    if (NULL != handle)
    {
        unsigned char command;
        command = startStop;
        unsigned char answer[65];
        cout << "Starting / stopping pattern sequence" << endl;
        sendCommand(DLPC900_CMD_WRITE, DLPC900_CMD_PATTERNSTARTSTOP,
                    &command, 1, answer);
    }
}

void DLPC900::setPattern()
{
    using namespace std;
    if (NULL != handle)
    {
        cout << "Setting pattern" << endl;

        unsigned char command_data[12];
        command_data[0] = 0x00;
        command_data[1] = 0x00;
        command_data[2] = 0xCE;
        command_data[3] = 0x0F;
        command_data[4] = 0x00;
        command_data[5] = 0x9F;
        command_data[6] = 0x00;
        command_data[7] = 0x00;
        command_data[8] = 0x00;
        command_data[9] = 0x00;
        command_data[10] = 0x00;
        command_data[11] = 0x00;
        unsigned char answer[65];
        sendCommand(DLPC900_CMD_WRITE, DLPC900_CMD_PATTERNLUTDEFINITION,
                    command_data, 12, answer);

        command_data[0] = 0x01;
        command_data[1] = 0x00;
        command_data[2] = 0xCE;
        command_data[3] = 0x0F;
        command_data[4] = 0x00;
        command_data[5] = 0x1F;
        command_data[6] = 0x00;
        command_data[7] = 0x00;
        command_data[8] = 0x00;
        command_data[9] = 0x00;
        command_data[10] = 0x00;
        command_data[11] = 0x40;
        sendCommand(DLPC900_CMD_WRITE, DLPC900_CMD_PATTERNLUTDEFINITION,
                    command_data, 12, answer);

        command_data[0] = 0x02;
        command_data[1] = 0x00;
        command_data[2] = 0xCE;
        command_data[3] = 0x0F;
        command_data[4] = 0x00;
        command_data[5] = 0x1F;
        command_data[6] = 0x00;
        command_data[7] = 0x00;
        command_data[8] = 0x00;
        command_data[9] = 0x00;
        command_data[10] = 0x00;
        command_data[11] = 0x80;
        sendCommand(DLPC900_CMD_WRITE, DLPC900_CMD_PATTERNLUTDEFINITION,
                    command_data, 12, answer);

        usleep(300000);
    }
}

void DLPC900::setPattern_FullWhite()
{
    using namespace std;
    if (NULL != handle)
    {
        cout << "Setting pattern" << endl;

        unsigned char command_data[12];
        command_data[0] = 0x00;
        command_data[1] = 0x00;
        command_data[2] = 0xCE;
        command_data[3] = 0x0F;
        command_data[4] = 0x00;
        command_data[5] = 0x7E; //01111110 
        command_data[6] = 0x00;
        command_data[7] = 0x00;
        command_data[8] = 0x00;
        command_data[9] = 0x01; //00000001
        command_data[10] = 0x00;
        command_data[11] = 0x00;
        unsigned char answer[65];
        sendCommand(DLPC900_CMD_WRITE, DLPC900_CMD_PATTERNLUTDEFINITION,
                    command_data, 12, answer);


        usleep(300000);
    }
}

void DLPC900::configPattern()
{
    using namespace std;
    if (NULL != handle)
    {
        unsigned char command_data[6];
        command_data[0] = 0x03;
        command_data[1] = 0x00;
        command_data[2] = 0x00;
        command_data[3] = 0x00;
        command_data[4] = 0x00;
        command_data[5] = 0x00;

        cout << "Configuring LUT" << endl;

        unsigned char answer[65];
        sendCommand(DLPC900_CMD_WRITE, DLPC900_CMD_LUTCONFIG, command_data, 6,
                    answer);
        sendCommand(DLPC900_CMD_WRITE, DLPC900_CMD_LUTCONFIG, command_data, 6,
                    answer);

        usleep(1000000);
    }
}

void DLPC900::configPattern_FullWhite()
{
    using namespace std;
    if (NULL != handle)
    {
        unsigned char command_data[6];
        command_data[0] = 0x01;
        command_data[1] = 0x00;
        command_data[2] = 0x00;
        command_data[3] = 0x00;
        command_data[4] = 0x00;
        command_data[5] = 0x00;

        cout << "Configuring LUT" << endl;

        unsigned char answer[65];
        sendCommand(DLPC900_CMD_WRITE, DLPC900_CMD_LUTCONFIG, command_data, 6,
                    answer);
        sendCommand(DLPC900_CMD_WRITE, DLPC900_CMD_LUTCONFIG, command_data, 6,
                    answer);

        usleep(1000000);
    }
}

void DLPC900::waitForLocking()
{
    using namespace std;
    if (NULL != handle)
    {
        auto start = chrono::steady_clock::now();
        while (DLPC900_VIDEO_NOTLOCKED == getLocking())
        {
            auto now = chrono::steady_clock::now();
            auto elapsed = chrono::duration_cast<chrono::seconds>(now - start).count();

            if (elapsed >= 10)
            {
                cout << "Timeout: Video signal locking took too long" << endl;
                return;
            }

            this_thread::sleep_for(chrono::milliseconds(100)); // Sleep for 100 milliseconds to avoid busy-waiting
        }
        cout << "Video signal is locked" << endl;
    }
}

void DLPC900::setLongAxisFlip(uint8_t on_off) //only works for flash images :(
{
    using namespace std;
    if (NULL != handle)
    {
        unsigned char command;
        command = on_off;
        unsigned char answer[65];
        cout << "Setting Long Axis Flip" << endl;
        sendCommand(DLPC900_CMD_WRITE, DLPC900_CMD_FLIP_LONG_AXIS , &command,
                    1, answer);
    }
}
