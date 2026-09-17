import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, result } from "../api/client";
import { Loading, Notice } from "../components";

export default function Accounts() {
  const client = useQueryClient();
  const accounts = useQuery({
    queryKey: ["accounts"],
    queryFn: async () => result(await api.GET("/api/auth/users")),
  });
  const create = useMutation({
    mutationFn: async (form: HTMLFormElement) => {
      const values = new FormData(form);
      const role = String(values.get("role")) as "admin" | "member" | "viewer";
      const response = result(
        await api.POST("/api/auth/users", {
          body: {
            username: String(values.get("username")),
            display_name: String(values.get("display_name")),
            password: String(values.get("password")),
            role,
          },
        }),
      );
      form.reset();
      return response;
    },
    onSuccess: () => client.invalidateQueries({ queryKey: ["accounts"] }),
  });
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">YOUR HOUSEHOLD</p>
          <h1>Accounts</h1>
          <p className="muted">Give each reader their own lists and access.</p>
        </div>
      </div>
      <form
        className="panel editor"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate(e.currentTarget);
        }}
      >
        <h2>Add an account</h2>
        <div className="form-row">
          <label>
            Name
            <input name="display_name" required maxLength={120} />
          </label>
          <label>
            Username
            <input
              name="username"
              autoComplete="off"
              required
              minLength={3}
              maxLength={100}
            />
          </label>
        </div>
        <div className="form-row">
          <label>
            Password
            <input
              name="password"
              type="password"
              required
              minLength={12}
              maxLength={256}
              autoComplete="new-password"
            />
          </label>
          <label>
            Access
            <select name="role" defaultValue="member">
              <option value="member">Member — manage own lists</option>
              <option value="viewer">Viewer — browse only</option>
              <option value="admin">Administrator — manage instance</option>
            </select>
          </label>
        </div>
        <button className="primary" disabled={create.isPending}>
          Create account
        </button>
        <Notice error={create.error} />
      </form>
      <Notice error={accounts.error} />
      {accounts.isPending ? (
        <Loading />
      ) : (
        <div className="panel account-list">
          {accounts.data?.map((user) => (
            <div key={user.id}>
              <div>
                <strong>{user.display_name}</strong>
                <p>{user.username}</p>
              </div>
              <span className="status">{user.role}</span>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
