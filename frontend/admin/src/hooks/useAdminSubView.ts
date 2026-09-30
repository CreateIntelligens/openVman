import { useCallback } from "react";
import type { Tab } from "../components/app/navigation";
import { useNavigation } from "../context/NavigationContext";

/** The route owns the visible panel; navigation retains the app's history and dirty guard. */
export function useAdminSubView<T extends string>(
  tab: Tab,
  defaultView: T,
  allowedViews: readonly T[],
): [T, (next: T) => void] {
  const { currentSubView, navigateTo } = useNavigation();
  const view = currentSubView && allowedViews.includes(currentSubView as T)
    ? currentSubView as T
    : defaultView;
  const setView = useCallback((next: T) => {
    if (next !== view && allowedViews.includes(next)) navigateTo(tab, next);
  }, [allowedViews, navigateTo, tab, view]);
  return [view, setView];
}
