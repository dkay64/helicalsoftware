#include <pylon/PylonIncludes.h>
#include <opencv2/opencv.hpp>
#include <QApplication>
#include <QLabel>
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QWidget>
#include <QSlider>
#include <QTimer>
#include <QScreen>
#include <QWindow>
#include <QPixmap>
#include <chrono>
#include <iostream>
#include <vector>
#include <tuple>
#include "ImageProcessingHelper.h"

// g++ -std=c++17 -o Cal_HorizontalLine_Merged Cal_HorizontalLine_Merged.cpp ImageProcessingHelper.cpp -lpylonbase -lpylonutility -lGenApi_gcc_v3_1_Basler_pylon -lGCBase_gcc_v3_1_Basler_pylon `pkg-config --cflags --libs opencv4` `pkg-config --cflags --libs Qt5Widgets` -lopencv_cudaimgproc -lopencv_cudafilters -lopencv_cudaarithm -lopencv_core -lopencv_highgui -lopencv_imgproc

using namespace Pylon;
using namespace std;
using namespace cv;

int main(int argc, char *argv[]) {
    QApplication app(argc, argv);

    // Initialize Pylon runtime
    PylonInitialize();

    try {
        // Create an instant camera object
        CInstantCamera camera(CTlFactory::GetInstance().CreateFirstDevice());

        // Open the camera and access its node map
        camera.Open();

        // Set pixel format to Mono8 (Grayscale)
        GenApi::INodeMap& nodemap = camera.GetNodeMap();
        GenApi::CEnumerationPtr pixelFormat = nodemap.GetNode("PixelFormat");

        if (GenApi::IsAvailable(pixelFormat) && GenApi::IsWritable(pixelFormat)) {
            pixelFormat->FromString("Mono8");
        } else {
            cerr << "PixelFormat Mono8 not available!" << endl;
        }

        // Set exposure time to 160 µs
        GenApi::CFloatPtr exposureTime = nodemap.GetNode("ExposureTime");
        if (GenApi::IsAvailable(exposureTime) && GenApi::IsWritable(exposureTime)) {
            exposureTime->SetValue(160.0);  // Set exposure time to 160 µs
        } else {
            cerr << "Failed to set ExposureTime!" << endl;
        }

        // Start grabbing images
        camera.StartGrabbing(GrabStrategy_LatestImageOnly);
        CGrabResultPtr ptrGrabResult;

        // Set up Qt window for displaying the camera output on Screen 0 (HDMI-0)
        QWidget window0;
        QVBoxLayout* mainLayout = new QVBoxLayout();
        QLabel* finalImage = new QLabel();
        QLabel* infoLabel = new QLabel("FPS: 0, Total Frames: 0");
        QLabel* thresholdValueLabel = new QLabel("Threshold: 7");
        QLabel* slopes = new QLabel("TOP: 0, BOT: 0");
        QSlider* thresholdSlider = new QSlider(Qt::Horizontal);
        thresholdSlider->setRange(0, 255);
        thresholdSlider->setValue(25);

        mainLayout->addWidget(finalImage);
        mainLayout->addWidget(infoLabel);
        mainLayout->addWidget(thresholdValueLabel);
        mainLayout->addWidget(thresholdSlider);
        mainLayout->addWidget(slopes);
        window0.setLayout(mainLayout);
        window0.setWindowTitle("Basler Camera - Display with Line Separation");

        // Set the size and show the window (not full screen)
        window0.resize(1280, 720);  // Resize to 1280x720
        window0.show();

        // Set the camera display window to Screen 0 (HDMI-0)
        QList<QScreen *> screens = QGuiApplication::screens();
        if (screens.size() > 0) {
            QScreen *screen0 = screens.at(0);  // Assuming HDMI-0 is the first screen
            QWindow *window = window0.windowHandle();
            if (window != nullptr) {
                window->setScreen(screen0);
                window->setGeometry(screen0->geometry());
            }
        }

        // Set up for the horizontal line display on Screen 1 (DP-0)
        QLabel label;  // Label to hold the horizontal line image
        QPixmap pixmap("/home/jacob/Desktop/Image Codes/centered_horizontal_line.png");
        label.setPixmap(pixmap);
        label.setScaledContents(true);
        label.show();

        if (screens.size() > 1) {
            QScreen *screen1 = screens.at(1);  // Assuming DP-0 is the second screen
            QWindow *window = label.windowHandle();
            if (window != nullptr) {
                window->setScreen(screen1);
                window->setGeometry(screen1->geometry());
                label.showFullScreen();
            }
        }

        // FPS calculation variables
        int total_frames = 0;
        int frames_in_last_second = 0;
        auto start_time = chrono::high_resolution_clock::now();

        Mat thresholded, cannyEdges, separatedLines, colorFrame, cameraOutputWithLines;
        Vec4f topfit, botfit;
        float TopSlope, BotSlope;

        // Set up QTimer for periodic updates
        QTimer timer;
        QObject::connect(&timer, &QTimer::timeout, [&]() {
            if (camera.IsGrabbing()) {
                camera.RetrieveResult(5000, ptrGrabResult, TimeoutHandling_ThrowException);
                if (ptrGrabResult->GrabSucceeded()) {
                    Mat frame(Size(ptrGrabResult->GetWidth(), ptrGrabResult->GetHeight()), CV_8UC1, (uint8_t*)ptrGrabResult->GetBuffer());

                    // Apply brightness threshold
                    int brightness_threshold = thresholdSlider->value();
                    thresholded = applyThreshold(frame, brightness_threshold);

                    // Apply Canny edge detection
                    cannyEdges = applyCanny(thresholded, 50, 150);

                    // Perform line separation
                    tie(separatedLines, topfit, botfit) = applyLineSeparation(cannyEdges);
                    TopSlope = topfit[1] / topfit[0];
                    BotSlope = botfit[1] / botfit[0];
                    slopes->setText(QString("TOP: %1, BOT: %2").arg(TopSlope).arg(BotSlope));

                    // Draw the line fits on the camera output image
                    cvtColor(frame, colorFrame, cv::COLOR_GRAY2RGB);
                    cameraOutputWithLines = drawLineFitsOnImage(colorFrame, topfit, botfit);

                    // Display final image
                    resize(cameraOutputWithLines, cameraOutputWithLines, Size(1280, 720));
                    QImage cameraOutputWithLinesQImage(cameraOutputWithLines.data, cameraOutputWithLines.cols, cameraOutputWithLines.rows, cameraOutputWithLines.step, QImage::Format_RGB888);
                    finalImage->setPixmap(QPixmap::fromImage(cameraOutputWithLinesQImage));

                    // Update labels
                    thresholdValueLabel->setText(QString("Threshold: %1").arg(brightness_threshold));

                    // FPS calculation
                    total_frames++;
                    frames_in_last_second++;
                    auto current_time = chrono::high_resolution_clock::now();
                    chrono::duration<double> elapsed = current_time - start_time;

                    if (elapsed.count() >= 1.0) {
                        double fps = frames_in_last_second / elapsed.count();
                        infoLabel->setText(QString("FPS: %1, Total Frames: %2").arg(fps).arg(total_frames));
                        frames_in_last_second = 0;
                        start_time = current_time;
                    }
                }
            }
        });
        timer.start(0);

        return app.exec();
    } catch (const GenericException &e) {
        cerr << "An exception occurred: " << e.GetDescription() << endl;
        PylonTerminate();
        return 1;
    }

    PylonTerminate();
    return 0;
}
