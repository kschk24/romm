<script setup lang="ts">
import type { Emitter } from "mitt";
import { inject, ref } from "vue";
import { useDisplay } from "vuetify";
import storeNotifications from "@/stores/notifications";
import type { Events, SnackbarStatus } from "@/types/emitter";

const show = ref(false);
const { xs } = useDisplay();
const snackbarStatus = ref<SnackbarStatus>({ msg: "" });
const queue = ref<SnackbarStatus[]>([]);
const notificationStore = storeNotifications();

// Event listeners bus
const emitter = inject<Emitter<Events>>("emitter");
emitter?.on("snackbarShow", (snackbar: SnackbarStatus) => {
  queue.value.push(snackbar);
  if (!show.value) showNext();
});

function showNext() {
  const next = queue.value.shift();
  if (!next) return;
  snackbarStatus.value = next;
  snackbarStatus.value.id = notificationStore.notifications.length + 1;
  show.value = true;
}

function closeDialog() {
  // Ignore duplicate close calls (e.g. manual close + Vuetify @timeout firing
  // for the same snackbar); otherwise the queue could advance twice and drop one.
  if (!show.value) return;
  notificationStore.remove(snackbarStatus.value.id);
  show.value = false;
  // Advance to the next queued snackbar after the close transition.
  if (queue.value.length > 0) {
    setTimeout(showNext, 300);
  }
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
