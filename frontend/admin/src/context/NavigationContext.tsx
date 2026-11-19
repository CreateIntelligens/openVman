import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  type ReactNode,
} from "react";

import type { KnowledgeLanguage } from "../api/knowledge";
import type { Tab } from "../components/app/navigation";

export interface ChatTestOptions {
  question?: string;
  language?: KnowledgeLanguage;
}

export interface ChatTestRequest {
  language?: KnowledgeLanguage;
  startFresh: boolean;
  takeQuestion: () => string | undefined;
}

export function createChatTestRequest({ question, language }: ChatTestOptions): ChatTestRequest {
  let pendingQuestion = question?.trim() || undefined;
  return {
    language,
    startFresh: Boolean(pendingQuestion),
    takeQuestion: () => {
      const value = pendingQuestion;
      pendingQuestion = undefined;
      return value;
    },
  };
}

interface NavigationContextType {
  navigateTo: (tab: Tab, subView?: string) => void;
  openChatTest: (options: ChatTestOptions) => void;
  chatTest?: ChatTestRequest;
  currentTab: Tab;
  currentSubView?: string;
}

const NavigationContext = createContext<NavigationContextType | undefined>(undefined);

type NavigationProviderProps = {
  children: ReactNode;
  currentTab: Tab;
  currentSubView?: string;
  onSelectTab: (tab: Tab, subView?: string) => void;
  chatTest?: ChatTestRequest;
  onOpenChatTest?: (options: ChatTestOptions) => void;
};

export function NavigationProvider({
  children,
  currentTab,
  currentSubView,
  onSelectTab,
  chatTest,
  onOpenChatTest,
}: NavigationProviderProps) {
  const navigateTo = useCallback(
    (tab: Tab, subView?: string) => {
      onSelectTab(tab, subView);
    },
    [onSelectTab],
  );

  const openChatTest = useCallback((options: ChatTestOptions) => {
    if (onOpenChatTest) onOpenChatTest(options);
    else navigateTo("Chat");
  }, [navigateTo, onOpenChatTest]);

  const value = useMemo(
    () => ({ navigateTo, openChatTest, chatTest, currentTab, currentSubView }),
    [chatTest, currentSubView, currentTab, navigateTo, openChatTest],
  );

  return (
    <NavigationContext.Provider value={value}>
      {children}
    </NavigationContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useNavigation() {
  const ctx = useContext(NavigationContext);
  if (!ctx) throw new Error("useNavigation must be used within NavigationProvider");
  return ctx;
}
