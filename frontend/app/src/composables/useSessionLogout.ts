import { ref } from "vue";
import { leaveFullscreen, runLogout } from "../sessionCleanup";
import { clearResumeSession } from "./sessionResume";
import { useAuth } from "./useAuth";

export function useSessionLogout() {
  const auth = useAuth();
  const loggingOut = ref(false);

  async function handleLogout(): Promise<void> {
    await runLogout({
      isLoggingOut: () => loggingOut.value,
      setLoggingOut: (value) => {
        loggingOut.value = value;
      },
      cleanup: () => {
        clearResumeSession();
        return leaveFullscreen();
      },
      logout: auth.logout,
    });
  }

  return { loggingOut, handleLogout };
}
