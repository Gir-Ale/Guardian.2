#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <ESP32Servo.h>
#include "driver/i2s.h"

// ---AUDIO PINS ---
#define I2S_BCLK D10
#define I2S_LRC  D9
#define I2S_DOUT D6

#define I2S_PORT I2S_NUM_0

// --- WIFI CONFIG ---
const char* ssid = "name";
const char* password = "*****";

// --- UDP CONFIG ---
WiFiUDP udp;
const int udpPort = 4210;
char incomingPacket[50];

WiFiUDP audioUdp;
const int audioPort = 4211;


// ===== L298N MOTOR PINS =====
// Motor 1 (Left)
const int motor1ENA = D5;   // PWM
const int motor1IN1 = D4;
const int motor1IN2 = D3;

// Motor 2 (Right)
const int motor2ENA = D0;   // PWM
const int motor2IN1 = D2;
const int motor2IN2 = D1;

// --- SERVO PINS ---
Servo servoPan;
Servo servoTilt;
const int servoPanPin = D8;
const int servoTiltPin = D7;

// --- SETUP ---
void setup() {
  Serial.begin(115200);

  // Motors
  pinMode(motor1ENA, OUTPUT);
  pinMode(motor1IN1, OUTPUT);
  pinMode(motor1IN2, OUTPUT);

  pinMode(motor2ENA, OUTPUT);
  pinMode(motor2IN1, OUTPUT);
  pinMode(motor2IN2, OUTPUT);

  // Stop motors initially
  analogWrite(motor1ENA, 0);
  analogWrite(motor2ENA, 0);

  // Servos
  servoPan.attach(servoPanPin);
  servoTilt.attach(servoTiltPin);

  // Wi-Fi
  Serial.print("Connecting to Wi-Fi...");
  WiFi.begin(ssid, password);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println("\nConnected!");
  Serial.print("IP address: ");
  Serial.println(WiFi.localIP());

  // Start UDP
  udp.begin(udpPort);
  Serial.print("Listening on UDP port ");
  Serial.println(udpPort);


  ///audio 

  i2s_config_t i2s_config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
    .sample_rate = 16000,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_I2S,
    .intr_alloc_flags = 0,
    .dma_buf_count = 8,
    .dma_buf_len = 256,
    .use_apll = false
  };

  i2s_pin_config_t pin_config = {
    .bck_io_num = I2S_BCLK,
    .ws_io_num = I2S_LRC,
    .data_out_num = I2S_DOUT,
    .data_in_num = I2S_PIN_NO_CHANGE
  };

  i2s_driver_install(I2S_PORT, &i2s_config, 0, NULL);
  i2s_set_pin(I2S_PORT, &pin_config);
  
  audioUdp.begin(audioPort);   
}

// --- LOOP ---
void loop() {

  int packetSize = udp.parsePacket();
  if (packetSize) {

    int len = udp.read(incomingPacket, 50);
    if (len > 0) {
      incomingPacket[len] = 0;
    }

    int motorX = 0;
    int motorY = 0;
    int servoX = 90;
    int servoY = 90;

    int res = sscanf(incomingPacket, "%d,%d,%d,%d",&motorX, &motorY, &servoX, &servoY);

    if (res == 4) {

      int leftSpeed  = motorY + motorX;
      int rightSpeed = motorY - motorX;

      setMotor(motor1ENA, motor1IN1, motor1IN2, leftSpeed);
      setMotor(motor2ENA, motor2IN1, motor2IN2, rightSpeed);

      servoPan.write(constrain(servoX, 0, 180));
      servoTilt.write(constrain(servoY, 0, 180));

      Serial.printf("Motors: L=%d R=%d | Servos: Pan=%d Tilt=%d\n",leftSpeed, rightSpeed, servoX, servoY);
    }
  }

  int audioPacket = audioUdp.parsePacket();
  if (audioPacket) {

    static uint8_t audioBuffer[512];

    int len = audioUdp.read(audioBuffer, sizeof(audioBuffer));

    size_t bytes_written;

    i2s_write(I2S_PORT, audioBuffer, len, &bytes_written, portMAX_DELAY);
  }
}

// ===== MOTOR FUNCTION (Same Style, L298N Compatible) =====
void setMotor(int pwmPin, int in1Pin, int in2Pin, int speed) {

  speed = constrain(speed, -255, 255);

  if (speed > 0) {
    digitalWrite(in1Pin, HIGH);
    digitalWrite(in2Pin, LOW);
    analogWrite(pwmPin, speed);
  }
  else if (speed < 0) {
    digitalWrite(in1Pin, LOW);
    digitalWrite(in2Pin, HIGH);
    analogWrite(pwmPin, -speed);
  }
  else {
    digitalWrite(in1Pin, LOW);
    digitalWrite(in2Pin, LOW);
    analogWrite(pwmPin, 0);
  }
}
