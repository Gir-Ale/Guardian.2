import socket
import pygame
import requests
import cv2
import numpy as np
import threading
import time
import soundcard as sc
import socket

# --- CONFIGURE ESP32 ---
XIAO_IP = "Enter the IP address of your ESP32 here" # <-- CHANGE THIS TO YOUR ESP32'S IP ADDRESS
ESP_PORT = 4210
ESP_IP = "Enter the IP address of your ESPCAM here" # <-- CHANGE THIS TO YOUR ESPCAM IP ADDRESS
STREAM_URL = "http://       :81/stream"       # <-- ADD YOUR ESPCAM IP ADDRESS instead of the spaces
CONTROL_URL = "http://       /control"        # <-- ADD YOUR ESPCAM IP ADDRESS instead of the spaces

# --- AUDIO STREAM ---
AUDIO_PORT = 4211

talking = False
samplerate = 16000
blocksize = 256
volume_level = 2.0

# --- UDP SOCKET ---
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
audio_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# --- INITIALIZE PYGAME ---
pygame.init()
info = pygame.display.Info()
WIDTH, HEIGHT = info.current_w, info.current_h
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("ROBOT CONTROL STATION")
clock = pygame.time.Clock()

font = pygame.font.Font(None, 24)
title_font = pygame.font.Font(None, 40)
hud_font = pygame.font.Font(None, 28)

# Robot state
motorX = 0
motorY = 0
servoX = 90
servoY = 90
zoom_level = 1.0

# Frame buffer
frame_surface = None

class Slider:
    def __init__(self, x, y, w, h, min_val, max_val, start_val, text):
        self.rect = pygame.Rect(x, y, w, h)
        self.min_val = min_val
        self.max_val = max_val
        self.val = start_val
        self.text = text
        self.dragging = False
        self.changed = False

    def draw(self, screen, font):
        pygame.draw.rect(screen, (80, 80, 80), self.rect, border_radius=self.rect.h//2)
        ratio = (self.val - self.min_val) / (self.max_val - self.min_val)
        handle_x = self.rect.x + int(ratio * self.rect.w)
        handle_y = self.rect.y + self.rect.h // 2
        pygame.draw.circle(screen, (200, 200, 200), (handle_x, handle_y), int(self.rect.h * 1.5))
        
        txt_surf = font.render(f"{self.text}: {int(self.val) if self.max_val > 5 else round(self.val, 1)}", True, (255, 255, 255))
        screen.blit(txt_surf, (self.rect.x, self.rect.y - 25))

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                collide_rect = self.rect.inflate(0, self.rect.h * 4)
                if collide_rect.collidepoint(event.pos):
                    self.dragging = True
                    self.update_val(event.pos[0])
                    return True
        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1:
                if self.dragging:
                    self.dragging = False
                    self.changed = True
                    return True
        elif event.type == pygame.MOUSEMOTION:
            if self.dragging:
                self.update_val(event.pos[0])
                return True
        return False

    def update_val(self, mx):
        rel_x = mx - self.rect.x
        rel_x = max(0, min(rel_x, self.rect.w))
        ratio = rel_x / self.rect.w
        self.val = self.min_val + ratio * (self.max_val - self.min_val)

RIGHT_MARGIN = 250
LEFT_MARGIN = 50

sliders = {
    "resolution": Slider(WIDTH - RIGHT_MARGIN, 200, 150, 8, 0, 15, 8, "Resolution"),
    "led": Slider(WIDTH - RIGHT_MARGIN, 300, 150, 8, 0, 255, 0, "LED Intensity"),
    "speed": Slider(WIDTH - RIGHT_MARGIN, 400, 150, 8, 150, 255, 200, "Speed"),
    "volume": Slider(WIDTH - RIGHT_MARGIN, 500, 150, 8, 0, 6, 2, "Mic Volume")
}

def send_esp_control(var, val):
    try:
        url = f"{CONTROL_URL}?var={var}&val={val}"
        requests.get(url, timeout=2)
    except Exception as e:
        print(f"Failed to set {var}: {e}")

# -------- VIDEO THREAD --------
def camera_stream():
    global frame_surface

    while True:
        try:
            print("Connecting to camera stream...")
            stream = requests.get(
                STREAM_URL,
                stream=True,
                timeout=5,
                headers={"Connection": "close"}
            )
            bytes_data = bytes()

            for chunk in stream.iter_content(chunk_size=1024):
                if not chunk:
                    raise Exception("Stream disconnected")

                bytes_data += chunk
                a = bytes_data.find(b'\xff\xd8')
                b = bytes_data.find(b'\xff\xd9')

                if a != -1 and b != -1:
                    jpg = bytes_data[a:b+2]
                    bytes_data = bytes_data[b+2:]

                    if len(jpg) == 0:
                        continue

                    img_array = np.frombuffer(jpg, dtype=np.uint8)
                    if img_array.size == 0:
                        continue

                    img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                    if img is None:
                        continue

                    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                    img = cv2.resize(img, (600, 800))
                    img_rotated = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)

                    frame_surface = pygame.surfarray.make_surface(
                        np.transpose(img_rotated, (1, 0, 2))
                    )

        except Exception as e:
            print("Camera disconnected. Reconnecting in 2 seconds...")
            frame_surface = None
            time.sleep(2)

# Start camera thread
threading.Thread(target=camera_stream, daemon=True).start()

def send_udp():
    msg = f"{motorX},{motorY},{servoX},{servoY}"
    sock.sendto(msg.encode(), (XIAO_IP, ESP_PORT))

def start_audio():
    global talking, volume_level
    chunk_size = 256
    was_talking = False
    
    try:
        # Get loopback (system audio)
        default_speaker = sc.default_speaker()
        mics = sc.all_microphones(include_loopback=True)
        loopback = None
        for m in mics:
            if m.name == default_speaker.name and m.isloopback:
                loopback = m
                break
                
        # Get default microphone (voice)
        default_mic = sc.default_microphone()
                
        if not loopback or not default_mic:
            print("Could not find both microphone and system audio loopback.")
            return

        with loopback.recorder(samplerate=samplerate, channels=1, blocksize=chunk_size) as loopback_mic, \
             default_mic.recorder(samplerate=samplerate, channels=1, blocksize=chunk_size) as voice_mic:
             
            while True:
                lb_data = loopback_mic.record(numframes=chunk_size)
                voice_data = voice_mic.record(numframes=chunk_size)
                
                if talking:
                    lb_mono = lb_data[:, 0]
                    voice_mono = voice_data[:, 0] if voice_data.shape[1] > 0 else np.zeros_like(lb_mono)
                    
                    mixed = lb_mono + voice_mono
                    
                    audio = mixed * volume_level * 32767.0
                    audio = np.clip(audio, -32768, 32767).astype(np.int16)
                    audio_sock.sendto(audio.tobytes(), (XIAO_IP, AUDIO_PORT))
                    was_talking = True
                elif was_talking:
                    empty_audio = np.zeros(chunk_size, dtype=np.int16)
                    for _ in range(20):
                        audio_sock.sendto(empty_audio.tobytes(), (XIAO_IP, AUDIO_PORT))
                        time.sleep(0.02)
                    was_talking = False
                    
    except Exception as e:
        print(f"Audio loopback error: {e}")

threading.Thread(target=start_audio, daemon=True).start()


# -------- MAIN LOOP --------
running = True
while running:

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_v:
                talking = True
            elif event.key == pygame.K_f:
                # Toggle LED between 0 and 255
                if sliders["led"].val > 0:
                    sliders["led"].val = 0
                else:
                    sliders["led"].val = 255
                threading.Thread(target=send_esp_control, args=("led_intensity", int(sliders["led"].val)), daemon=True).start()
            elif event.key == pygame.K_ESCAPE:
                running = False

        if event.type == pygame.KEYUP:
            if event.key == pygame.K_v:
                talking = False

        if event.type == pygame.MOUSEWHEEL:
            zoom_level += event.y * 0.1
            zoom_level = max(0.2, min(zoom_level, 5.0))

        for key, slider in sliders.items():
            slider.handle_event(event)
            if slider.changed:
                slider.changed = False
                if key == "resolution":
                    threading.Thread(target=send_esp_control, args=("framesize", int(slider.val)), daemon=True).start()
                elif key == "led":
                    threading.Thread(target=send_esp_control, args=("led_intensity", int(slider.val)), daemon=True).start()

    # ZQSD Controls → Motors
    keys = pygame.key.get_pressed()
    
    motorX = 0
    motorY = 0
    
    # Update volume and speed dynamically
    volume_level = sliders["volume"].val
    speed = int(sliders["speed"].val)

    if keys[pygame.K_s]:
        motorY = speed
    if keys[pygame.K_z]:
        motorY = -speed
    if keys[pygame.K_q]:
        motorX = -speed
    if keys[pygame.K_d]:
        motorX = speed

    # Mouse → Servo
    mx, my = pygame.mouse.get_pos()
    servoX = 180 - int((mx / WIDTH) * 140)
    servoY = 166 - int((my / HEIGHT) * 80)

    send_udp()

    # ========================================================
    # ===================== DRAW =============================
    # ========================================================

    screen.fill((15, 15, 20))

    if frame_surface:
        w, h = frame_surface.get_size()
        new_w, new_h = int(w * zoom_level), int(h * zoom_level)
        scaled_frame = pygame.transform.scale(frame_surface, (new_w, new_h))
        rect = scaled_frame.get_rect(center=(WIDTH//2, HEIGHT//2))
        screen.blit(scaled_frame, rect)
    else:
        text = title_font.render("NO CAMERA SIGNAL", True, (255, 80, 80))
        screen.blit(text, (WIDTH//2 - text.get_width()//2, HEIGHT//2))

    # HUD - Left side vitals
    screen.blit(title_font.render("Guardian .2", True, (255, 255, 255)), (LEFT_MARGIN, 40))
    
    # Connection dot
    pygame.draw.circle(screen, (0, 255, 0), (LEFT_MARGIN + 10, 100), 8)
    screen.blit(hud_font.render("CONNECTED", True, (0, 255, 0)), (LEFT_MARGIN + 25, 91))

    # IP
    screen.blit(hud_font.render(f"IP: {XIAO_IP}", True, (200, 200, 200)), (LEFT_MARGIN, 130))
    # Motors
    screen.blit(hud_font.render(f"Motor X: {motorX:4d}", True, (100, 255, 100)), (LEFT_MARGIN, 170))
    screen.blit(hud_font.render(f"Motor Y: {motorY:4d}", True, (100, 255, 100)), (LEFT_MARGIN, 200))
    # Servos
    screen.blit(hud_font.render(f"Pan: {servoX}°", True, (255, 255, 0)), (LEFT_MARGIN, 240))
    screen.blit(hud_font.render(f"Tilt: {servoY}°", True, (255, 255, 0)), (LEFT_MARGIN, 270))

    # TALKING INDICATOR (Left side, below vitals)
    if talking:
        pygame.draw.circle(screen, (255, 0, 0), (LEFT_MARGIN + 10, 330), 12)
        screen.blit(hud_font.render("TALKING", True, (255, 0, 0)), (LEFT_MARGIN + 30, 320))
    else:
        pygame.draw.circle(screen, (60, 0, 0), (LEFT_MARGIN + 10, 330), 12)
        screen.blit(hud_font.render("MIC MUTED", True, (100, 100, 100)), (LEFT_MARGIN + 30, 320))

    # Sliders - Right side
    for slider in sliders.values():
        slider.draw(screen, font)

    pygame.display.update()
    clock.tick(30)

pygame.quit()