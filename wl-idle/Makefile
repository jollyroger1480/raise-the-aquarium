PROTO = /usr/share/wayland-protocols/staging/ext-idle-notify/ext-idle-notify-v1.xml

aquarium-wl-idle: aquarium-wl-idle.c ext-idle-notify-v1.c ext-idle-notify-v1-client.h
	cc -O2 -Wall -o aquarium-wl-idle aquarium-wl-idle.c ext-idle-notify-v1.c `pkg-config --cflags --libs wayland-client`

ext-idle-notify-v1-client.h:
	wayland-scanner client-header $(PROTO) ext-idle-notify-v1-client.h

ext-idle-notify-v1.c:
	wayland-scanner private-code $(PROTO) ext-idle-notify-v1.c
