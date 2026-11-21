import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/endpoints";

export function useTeams() {
  const q = useQuery({ queryKey: ["teams"], queryFn: api.teams, staleTime: 5 * 60_000 });
  const byId = new Map((q.data ?? []).map((t) => [t.id, t.name]));
  return { ...q, teams: q.data ?? [], teamName: (id?: string | null) => (id ? (byId.get(id) ?? id.slice(0, 8)) : "—") };
}
