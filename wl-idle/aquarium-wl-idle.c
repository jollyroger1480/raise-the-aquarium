/*
 * aquarium-wl-idle: report compositor idle state over stdout.
 *
 * Uses the Wayland ext-idle-notify-v1 protocol. Unlike xscreensaver's own
 * XWayland-only idle timer, the compositor's idle notification
 *   - sees input to native Wayland windows, and
 *   - honours Wayland idle inhibitors (video players, browsers).
 *
 * Usage: aquarium-wl-idle TIMEOUT_MS
 * Prints "ready", then "idle" / "active" lines (flushed) as the state changes.
 * Exits 2 if the compositor does not offer ext_idle_notifier_v1.
 *
 * Build: see Makefile (cc ... -lwayland-client)
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wayland-client.h>
#include "ext-idle-notify-v1-client.h"

static struct ext_idle_notifier_v1 *notifier;
static struct wl_seat *seat;

static void reg_global(void *d, struct wl_registry *r, uint32_t name,
                       const char *iface, uint32_t ver) {
  (void)d;
  if (strcmp(iface, ext_idle_notifier_v1_interface.name) == 0)
    notifier = wl_registry_bind(r, name, &ext_idle_notifier_v1_interface, 1);
  else if (strcmp(iface, wl_seat_interface.name) == 0 && !seat)
    seat = wl_registry_bind(r, name, &wl_seat_interface, ver < 1 ? ver : 1);
}
static void reg_remove(void *d, struct wl_registry *r, uint32_t n) {
  (void)d; (void)r; (void)n;
}
static const struct wl_registry_listener reg_l = {reg_global, reg_remove};

static void on_idled(void *d, struct ext_idle_notification_v1 *n) {
  (void)d; (void)n;
  puts("idle");
  fflush(stdout);
}
static void on_resumed(void *d, struct ext_idle_notification_v1 *n) {
  (void)d; (void)n;
  puts("active");
  fflush(stdout);
}
static const struct ext_idle_notification_v1_listener idle_l = {on_idled,
                                                                on_resumed};

int main(int argc, char **argv) {
  long ms = argc > 1 ? strtol(argv[1], NULL, 10) : 30000;
  if (ms < 1000) ms = 1000;
  struct wl_display *dpy = wl_display_connect(NULL);
  if (!dpy) {
    fprintf(stderr, "aquarium-wl-idle: cannot connect to Wayland display\n");
    return 1;
  }
  struct wl_registry *reg = wl_display_get_registry(dpy);
  wl_registry_add_listener(reg, &reg_l, NULL);
  wl_display_roundtrip(dpy);
  if (!notifier || !seat) {
    fprintf(stderr, "aquarium-wl-idle: compositor lacks %s\n",
            !notifier ? "ext_idle_notifier_v1" : "wl_seat");
    return 2;
  }
  struct ext_idle_notification_v1 *n =
      ext_idle_notifier_v1_get_idle_notification(notifier, (uint32_t)ms, seat);
  ext_idle_notification_v1_add_listener(n, &idle_l, NULL);
  wl_display_roundtrip(dpy);
  puts("ready");
  fflush(stdout);
  while (wl_display_dispatch(dpy) != -1) {
  }
  return 0;
}
