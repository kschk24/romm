<script setup lang="ts">
import type { Emitter } from "mitt";
import { inject, ref, watch } from "vue";
import { useDisplay } from "vuetify";
import storeNotifications from "@/stores/notifications";
import type { Events, SnackbarStatus } from "@/types/emitter";

const show = ref(false);
const { xs } = useDisplay();
const snackbarStatus = ref<SnackbarStatus>({ msg: "" });
const queue = ref<SnackbarStatus[]>([]);
const notificationStore = storeNotifications();
// Pending close→open transition timer. Guards against advancing the queue
// twice (once immediately on a new event, once when this timer fires), which
// could replace a just-shown snackbar before it had its full display time.
let advanceTimer: ReturnType<typeof setTimeout> | null = null;

// Event listeners bus
const emitter = inject<Emitter<Events>>("emitter");
emitter?.on("snackbarShow", (snackbar: SnackbarStatus) => {
  queue.value.push(snackbar);
  // Only show immediately if nothing is visible and no advance is already
  // scheduled; otherwise let the existing path drain the queue.
  if (!show.value && advanceTimer === null) showNext();
});

function showNext() {
  const next = queue.value.shift();
  if (!next) return;
  snackbarStatus.value = next;
  snackbarStatus.value.id = notificationStore.notifications.length + 1;
  show.value = true;
}

// Advance the queue whenever the snackbar closes. Driving this off `show`
// (rather than the close handler) makes it robust to every close path —
// the timeout (which flips `show` via v-model before firing @timeout), the
// manual close button, and swipe/esc — so queued snackbars are never dropped.
watch(show, (visible) => {
  if (!visible && queue.value.length > 0 && advanceTimer === null) {
    // Small gap so the close transition finishes before the next appears.
    advanceTimer = setTimeout(() => {
      advanceTimer = null;
      showNext();
    }, 300);
  }
});

function closeDialog() {
  notificationStore.remove(snackbarStatus.value.id);
  show.value = false;
}
</script>

<template>
  <v-snackbar
    v-model="show"
    transition="scroll-y-transition"
    :timeout="snackbarStatus.timeout || 3000"
    absolute
    :location="xs ? 'top' : 'top right'"
    color="primary-darken"
    @timeout="closeDialog"
  >
    <template #text>
      <v-row class="d-flex align-start flex-row flex-nowrap px-2">
        <v-icon :icon="snackbarStatus.icon" class="mx-2 mt-1" />
        <span class="text-subtitle-1 font-weight-regular">
          {{ snackbarStatus.msg }}
        </span>
      </v-row>
    </template>
    <template #actions>
      <v-btn variant="text" @click="closeDialog">
        <v-icon icon="mdi-close" />
      </v-btn>
    </template>
  </v-snackbar>
</template>
