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
#include "ImageProcessingHelper.h"  // Include the helper functions

// g++ -std=c++17 -o Cal_Dot2 Cal_Dot2.cpp ImageProcessingHelper.cpp -lpylonbase -lpylonutility -lGenApi_gcc_v3_1_Basler_pylon -lGCBase_gcc_v3_1_Basler_pylon `pkg-config --cflags --libs opencv4` `pkg-config --cflags --libs Qt5Widgets` -lopencv_cudaimgproc -lopencv_cudafilters -lopencv_cudaarithm -lopencv_core -lopencv_highgui -lopencv_imgproc

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
        QLabel* whitePixelLabel = new QLabel("White Pixels: 0");
        QLabel* xyLabel = new QLabel("X: 0, Y: 0");  // To display the X, Y coordinates

        QSlider* thresholdSlider = new QSlider(Qt::Horizontal);
        thresholdSlider->setRange(0, 255);
        thresholdSlider->setValue(25);

        mainLayout->addWidget(finalImage);
        mainLayout->addWidget(infoLabel);
        mainLayout->addWidget(thresholdValueLabel);
        mainLayout->addWidget(thresholdSlider);
        mainLayout->addWidget(whitePixelLabel);
        mainLayout->addWidget(xyLabel);
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

        // Set up for the cal dot on DP-0
        Mat dotImage = createBlackImageWithWhiteSquare(1280, 800, 5); // Create a black image with a white pixel at (1280, 800)
        QImage qImg(dotImage.data, dotImage.cols, dotImage.rows, dotImage.step, QImage::Format_Grayscale8);
        QPixmap pixmap = QPixmap::fromImage(qImg);
        QLabel label;  // Label to hold the cal dot image
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

        Mat thresholded, cameraOutput;

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
                    thresholdValueLabel->setText(QString("Threshold: %1").arg(brightness_threshold));

                    // Get the average location of white pixels and the total count
                    cv::Point whitePixelCenter;
                    int totalWhitePixels;
                    tie(whitePixelCenter, totalWhitePixels) = calculateWhitePixelCenter(thresholded);

                    // Display the number of white pixels
                    whitePixelLabel->setText(QString("White Pixels: %1").arg(totalWhitePixels));

                    // Display the X and Y location
                    xyLabel->setText(QString("X: %1, Y: %2").arg(whitePixelCenter.x).arg(whitePixelCenter.y));

                    // Convert the frame to color for displaying the red dot
                    cvtColor(frame, cameraOutput, cv::COLOR_GRAY2BGR);

                    // Draw the red dot at the center of white pixels
                    if (totalWhitePixels > 0) {
                        cv::circle(cameraOutput, whitePixelCenter, 5, cv::Scalar(0, 0, 255), -1);  // Red dot with radius 5
                    }

                    // Display final image
                    resize(cameraOutput, cameraOutput, Size(1280, 720));
                    QImage frameQImage(cameraOutput.data, cameraOutput.cols, cameraOutput.rows, cameraOutput.step, QImage::Format_RGB888);  // Convert to RGB for display
                    finalImage->setPixmap(QPixmap::fromImage(frameQImage));

                    // Update FPS calculation
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
