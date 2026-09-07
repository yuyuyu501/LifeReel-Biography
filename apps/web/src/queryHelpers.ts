export interface QueryLike {
  isPending: boolean;
  isError: boolean;
  error: unknown;
  refetch: () => unknown;
}

export function hasQueryIssue(queries: QueryLike[]) {
  return queries.some((query) => query.isPending || query.isError);
}
