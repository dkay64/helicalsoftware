#include "ImageProcessingHelper.h"
#include <opencv2/opencv.hpp>
#include <vector>
#include <tuple>
#include <QImage>
#include <iostream>

// Convert OpenCV Mat to QImage
QImage Mat2QImage(const cv::Mat& mat) {
    QImage qimg(mat.data, mat.cols, mat.rows, mat.step, QImage::Format_Grayscale8);
    return qimg.copy();  // Ensure memory is managed correctly
}

// Apply binary threshold
cv::Mat applyThreshold(const cv::Mat& mat, int thresholdValue) {
    cv::Mat thresholded;
    cv::threshold(mat, thresholded, thresholdValue, 255, cv::THRESH_BINARY);  // Binary threshold
    return thresholded;
}

// Apply Morphological Opening
cv::Mat applyMorphOpen(const cv::Mat& mat) {
    cv::Mat morphOpened;
    cv::Mat kernel = cv::getStructuringElement(cv::MORPH_RECT, cv::Size(3, 3));
    cv::morphologyEx(mat, morphOpened, cv::MORPH_OPEN, kernel);  // Apply morphological open operation
    return morphOpened;
}

// Apply Canny edge detection
cv::Mat applyCanny(const cv::Mat& mat, int lowThreshold, int highThreshold) {
    cv::Mat edges;
    cv::Canny(mat, edges, lowThreshold, highThreshold);  // Apply Canny edge detection
    return edges;
}

// Apply line separation and return a tuple with separated image, top, and bottom line fits
std::tuple<cv::Mat, cv::Vec4f, cv::Vec4f> applyLineSeparation(const cv::Mat& edges) {
    // Find non-zero points from the Canny edge image
    std::vector<cv::Point> points;
    cv::findNonZero(edges, points);

    // Check if there are enough points to fit a line
    if (points.size() < 2) {
        // Not enough points, return a blank image and zero vectors
        return std::make_tuple(cv::Mat::zeros(edges.size(), CV_8UC3), cv::Vec4f(0, 0, 0, 0), cv::Vec4f(0, 0, 0, 0));
    }

    // Fit a line to all points using linear regression
    cv::Vec4f lineFit;
    cv::fitLine(points, lineFit, cv::DIST_L2, 0, 0.01, 0.01);

    // Line equation: y = mx + b
    float slope = lineFit[1] / lineFit[0];
    float intercept = lineFit[3] - slope * lineFit[2];

    // Create vectors for top and bottom points
    std::vector<cv::Point> topPoints;
    std::vector<cv::Point> bottomPoints;

    // Create an output image with colored points above and below the line
    cv::Mat colorSeparated(edges.size(), CV_8UC3, cv::Scalar(0, 0, 0));
    for (const cv::Point& pt : points) {
        float yFit = slope * pt.x + intercept;
        if (pt.y < yFit) {
            topPoints.push_back(pt);  // Add to top points
            colorSeparated.at<cv::Vec3b>(pt) = cv::Vec3b(0, 0, 255);  // Red for points above the line
        } else {
            bottomPoints.push_back(pt);  // Add to bottom points
            colorSeparated.at<cv::Vec3b>(pt) = cv::Vec3b(0, 255, 0);  // Green for points below the line
        }
    }

    // Check if there are enough top and bottom points for line fitting
    cv::Vec4f topLineFit, bottomLineFit;
    if (topPoints.size() > 1) {
        cv::fitLine(topPoints, topLineFit, cv::DIST_L2, 0, 0.01, 0.01);  // Fit line to top points
    } else {
        topLineFit = cv::Vec4f(0, 0, 0, 0);  // Return zero vector if not enough points
    }
    if (bottomPoints.size() > 1) {
        cv::fitLine(bottomPoints, bottomLineFit, cv::DIST_L2, 0, 0.01, 0.01);  // Fit line to bottom points
    } else {
        bottomLineFit = cv::Vec4f(0, 0, 0, 0);  // Return zero vector if not enough points
    }

    // Return the separated image and the top/bottom line fits
    return std::make_tuple(colorSeparated, topLineFit, bottomLineFit);
}

// Draw line fits on the camera output image
cv::Mat drawLineFitsOnImage(const cv::Mat& cameraOutput, const cv::Vec4f& topFit, const cv::Vec4f& bottomFit) {
    // Create a copy of the original image to draw the lines on
    cv::Mat outputImage = cameraOutput.clone();
    
    // Define a function to calculate the line endpoints for display
    auto calculateLineEndpoints = [](const cv::Vec4f& lineFit, int imgWidth) -> std::pair<cv::Point, cv::Point> {
        float slope = lineFit[1] / lineFit[0];
        float intercept = lineFit[3] - slope * lineFit[2];
        // Calculate the start and end points based on the image width
        cv::Point pt1(0, intercept); // At x = 0
        cv::Point pt2(imgWidth, slope * imgWidth + intercept); // At x = image width
        return std::make_pair(pt1, pt2);
    };

    // Draw the top line fit if it's valid
    if (topFit != cv::Vec4f(0, 0, 0, 0)) {
        auto [topPt1, topPt2] = calculateLineEndpoints(topFit, outputImage.cols);
        cv::line(outputImage, topPt1, topPt2, cv::Scalar(255, 0, 0), 2); // Draw top line in blue
    }

    // Draw the bottom line fit if it's valid
    if (bottomFit != cv::Vec4f(0, 0, 0, 0)) {
        auto [botPt1, botPt2] = calculateLineEndpoints(bottomFit, outputImage.cols);
        cv::line(outputImage, botPt1, botPt2, cv::Scalar(0, 255, 0), 2); // Draw bottom line in green
    }

    // Return the modified image with lines drawn
    return outputImage;
}

// Create a 2560x1600 black image with a square of white pixels of a given side length at (x, y)
cv::Mat createBlackImageWithWhiteSquare(int x, int y, int sideLength) {
    // Ensure the side length is an odd number
    if (sideLength % 2 == 0) {
        std::cout << "Side length is even. Increasing by 1 to make it odd." << std::endl;
        sideLength += 1;  // If it's even, increment to make it odd
    }

    // Create a 2560x1600 black image
    cv::Mat image = cv::Mat::zeros(1600, 2560, CV_8UC1);  // 8-bit single channel (grayscale)

	// Calculate the half size of the square
	int halfSize = (sideLength - 1) / 2;  // Ensures proper range for odd side lengths

	// Draw the white square, ensuring it doesn't go out of bounds
	for (int i = -halfSize; i <= halfSize; ++i) {
		for (int j = -halfSize; j <= halfSize; ++j) {
			int posX = x + i;
			int posY = y + j;
			if (posX >= 0 && posX < 2560 && posY >= 0 && posY < 1600) {
				image.at<uchar>(posY, posX) = 255;  // Set the pixel to white (255)
			}
		}
	}

    return image;
}

// Helper function to calculate the average location of white pixels and count them
std::tuple<cv::Point, int> calculateWhitePixelCenter(const cv::Mat& thresholdedImage) {
    int totalWhitePixels = 0;
    int sumX = 0, sumY = 0;

    // Iterate over each pixel in the thresholded image
    for (int y = 0; y < thresholdedImage.rows; ++y) {
        for (int x = 0; x < thresholdedImage.cols; ++x) {
            if (thresholdedImage.at<uchar>(y, x) == 255) {  // White pixel
                sumX += x;
                sumY += y;
                totalWhitePixels++;
            }
        }
    }

    // Calculate the average location
    cv::Point center(0, 0);
    if (totalWhitePixels > 0) {
        center.x = sumX / totalWhitePixels;
        center.y = sumY / totalWhitePixels;
    }

    return std::make_tuple(center, totalWhitePixels);
}
