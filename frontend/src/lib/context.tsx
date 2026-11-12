import { createContext, useContext, useState, type ReactNode } from "react";
import { store } from "./utils";

type User = { username: string; role: string } | null;
type Ctx = {
  user: User; setUser: (u: User) => void;
  project: string; setProject: (p: string) => void;
  lastImpact: any | null; setLastImpact: (r: any) => void;
};
const C = createContext<Ctx>(null as unknown as Ctx);

export function AppProvider({ children }: { children: ReactNode }) {
  const saved = store("eis.user");
  const [user, setUserState] = useState<User>(saved ? JSON.parse(saved) : null);
  const [project, setProjectState] = useState(store("eis.project") ?? "demo");
  const [lastImpact, setLastImpact] = useState<any | null>(null);
  const setUser = (u: User) => { setUserState(u); store("eis.user", u ? JSON.stringify(u) : null); };
  const setProject = (p: string) => { setProjectState(p); store("eis.project", p); };
  return <C.Provider value={{ user, setUser, project, setProject, lastImpact, setLastImpact }}>{children}</C.Provider>;
}
export const useApp = () => useContext(C);
