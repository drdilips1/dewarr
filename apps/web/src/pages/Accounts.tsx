import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, result, setCsrf, type Auth } from "../api/client";
import type { components } from "../api/schema";
import BookDialog from "../components/BookDialog";
import { Loading, Notice } from "../components";

type User = components["schemas"]["UserView"];
type Catalog = components["schemas"]["AccessCatalog"];
type Role = components["schemas"]["RoleView"];
type PresetRole = "admin" | "member" | "viewer" | "requester" | "approver";
type Editor =
  | { kind: "add" }
  | { kind: "user"; id: string }
  | { kind: "role"; id: string | null };

const presetRoles = new Set<PresetRole>([
  "admin",
  "member",
  "viewer",
  "requester",
  "approver",
]);

export default function Accounts({ embedded = false }: { embedded?: boolean }) {
  const client = useQueryClient();
  const session = useQuery({
    queryKey: ["session"],
    queryFn: async () => {
      const response = await api.GET("/api/auth/me");
      if (response.response.status === 401) return null;
      const auth = result(response);
      setCsrf(auth.csrf_token);
      return auth;
    },
  });
  const accounts = useQuery({
    queryKey: ["accounts"],
    queryFn: async () => result(await api.GET("/api/auth/users")),
  });
  const catalog = useQuery({
    queryKey: ["access-catalog"],
    queryFn: async () => result(await api.GET("/api/auth/access")),
  });
  const [panel, setPanel] = useState<"users" | "roles">("users");
  const usersTab = useRef<HTMLButtonElement>(null);
  const rolesTab = useRef<HTMLButtonElement>(null);
  function moveTab(next: "users" | "roles") {
    setPanel(next);
    (next === "users" ? usersTab : rolesTab).current?.focus();
  }
  const [editor, setEditor] = useState<Editor | null>(null);
  const [banner, setBanner] = useState<string | null>(null);
  const actor = (session.data as Auth | null | undefined)?.user;
  const selfId = actor?.id;
  const held = actor?.role === "admin" ? null : (actor?.permissions ?? []);
  const people = [...(accounts.data ?? [])].sort((a, b) => {
    if (a.id === selfId) return -1;
    if (b.id === selfId) return 1;
    return a.display_name.localeCompare(b.display_name);
  });
  const editing = people.find(
    (user) => user.id === (editor?.kind === "user" ? editor.id : ""),
  );
  const editingRole =
    editor?.kind === "role" && editor.id
      ? catalog.data?.roles.find((role) => role.id === editor.id)
      : null;

  return (
    <div className="access-page">
      {!embedded && (
        <div className="page-heading">
          <div>
            <p className="eyebrow">YOUR HOUSEHOLD</p>
            <h1>Accounts</h1>
          </div>
        </div>
      )}
      <div className="access-toolbar">
        <div
          className="access-switch"
          role="tablist"
          aria-label="Users and roles"
        >
          <button
            ref={usersTab}
            type="button"
            role="tab"
            id="access-users-tab"
            aria-selected={panel === "users"}
            aria-controls="access-users-panel"
            tabIndex={panel === "users" ? 0 : -1}
            onClick={() => setPanel("users")}
            onKeyDown={(event) => {
              if (event.key !== "ArrowRight" && event.key !== "ArrowLeft")
                return;
              event.preventDefault();
              moveTab(event.key === "ArrowRight" ? "roles" : "users");
            }}
          >
            Users
          </button>
          <button
            ref={rolesTab}
            type="button"
            role="tab"
            id="access-roles-tab"
            aria-selected={panel === "roles"}
            aria-controls="access-roles-panel"
            tabIndex={panel === "roles" ? 0 : -1}
            onClick={() => setPanel("roles")}
            onKeyDown={(event) => {
              if (event.key !== "ArrowRight" && event.key !== "ArrowLeft")
                return;
              event.preventDefault();
              moveTab(event.key === "ArrowRight" ? "roles" : "users");
            }}
          >
            Roles
          </button>
        </div>
        {panel === "users" ? (
          <button
            type="button"
            className="primary"
            disabled={!catalog.data}
            onClick={() => {
              setBanner(null);
              setEditor({ kind: "add" });
            }}
          >
            Add user
          </button>
        ) : (
          <button
            type="button"
            className="primary"
            disabled={!catalog.data}
            onClick={() => {
              setBanner(null);
              setEditor({ kind: "role", id: null });
            }}
          >
            New role
          </button>
        )}
      </div>
      <p className="access-lead">
        {panel === "users"
          ? "Add a person, then set what they can request and download."
          : "Built-in roles are ready to assign. A custom role is a shared set you can edit in one place."}
      </p>
      <Notice error={accounts.error || catalog.error} />
      {banner && <Notice error={new Error(banner)} />}
      {accounts.isPending ? (
        <Loading />
      ) : panel === "users" ? (
        <div
          id="access-users-panel"
          role="tabpanel"
          aria-labelledby="access-users-tab"
        >
          <UsersTable
            people={people}
            selfId={selfId}
            canManageAdmins={actor?.role === "admin"}
            onEdit={(id) => {
              setBanner(null);
              setEditor({ kind: "user", id });
            }}
          />
        </div>
      ) : catalog.isPending ? (
        <Loading />
      ) : (
        catalog.data && (
          <div
            id="access-roles-panel"
            role="tabpanel"
            aria-labelledby="access-roles-tab"
          >
            <RolesTable
              catalog={catalog.data}
              people={people}
              onEdit={(id) => {
                setBanner(null);
                setEditor({ kind: "role", id });
              }}
            />
          </div>
        )
      )}
      {editor?.kind === "add" && catalog.data && (
        <AddUserDialog
          catalog={catalog.data}
          held={held}
          close={() => setEditor(null)}
          onLinked={(message) => setBanner(message)}
        />
      )}
      {editor?.kind === "user" && catalog.data && editing && (
        <EditUserDialog
          key={editing.id}
          user={editing}
          catalog={catalog.data}
          held={held}
          selfId={selfId}
          close={() => setEditor(null)}
        />
      )}
      {editor?.kind === "role" &&
        catalog.data &&
        (editor.id === null || editingRole) && (
          <RoleDialog
            key={editingRole?.id ?? "new"}
            role={editingRole ?? null}
            catalog={catalog.data}
            held={held}
            close={() => setEditor(null)}
            onSaved={() => client.invalidateQueries({ queryKey: ["accounts"] })}
          />
        )}
    </div>
  );
}

function UsersTable({
  people,
  selfId,
  canManageAdmins,
  onEdit,
}: {
  people: User[];
  selfId?: string;
  canManageAdmins: boolean;
  onEdit: (id: string) => void;
}) {
  return (
    <div className="access-table-scroll">
      <table className="access-table access-table-users">
        <caption className="sr-only">Users</caption>
        <thead>
          <tr>
            <th scope="col">Name</th>
            <th scope="col">Username</th>
            <th scope="col">Role</th>
            <th scope="col">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {people.map((user) => (
            <tr key={user.id}>
              <td>
                <span className="access-name">{user.display_name}</span>
                {user.id === selfId && <span className="access-you">You</span>}
                <span className="access-username access-username-inline">
                  {user.username}
                </span>
              </td>
              <td className="access-username">{user.username}</td>
              <td>{user.access_label}</td>
              <td>
                {(canManageAdmins || user.role !== "admin") && (
                  <button
                    type="button"
                    aria-label={`Edit ${user.display_name}`}
                    onClick={() => onEdit(user.id)}
                  >
                    Edit
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RolesTable({
  catalog,
  people,
  onEdit,
}: {
  catalog: Catalog;
  people: User[];
  onEdit: (id: string) => void;
}) {
  const customPeople = people.filter(
    (user) => !user.permission_role_id && user.access_label === "Custom",
  ).length;
  return (
    <>
      <div className="access-table-scroll">
        <table className="access-table access-table-roles">
          <caption className="sr-only">Roles</caption>
          <thead>
            <tr>
              <th scope="col">Role</th>
              <th scope="col">People</th>
              <th scope="col">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {catalog.presets.map((preset) => (
              <tr key={preset.id}>
                <td>
                  <div className="access-name">{preset.label}</div>
                  <div className="access-meta">{preset.description}</div>
                </td>
                <td>{countLabel(presetPeople(people, preset.label))}</td>
                <td>
                  <span className="access-meta">Built-in</span>
                </td>
              </tr>
            ))}
            {catalog.roles.map((role) => (
              <tr key={role.id}>
                <td>
                  <div className="access-name">{role.name}</div>
                  {role.description && (
                    <div className="access-meta">{role.description}</div>
                  )}
                </td>
                <td>{countLabel(rolePeople(people, role.id))}</td>
                <td>
                  <button
                    type="button"
                    aria-label={`Edit ${role.name}`}
                    onClick={() => onEdit(role.id)}
                  >
                    Edit
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {customPeople > 0 && (
        <p className="access-lead">
          {countLabel(customPeople)} {customPeople === 1 ? "has" : "have"}{" "}
          permissions that do not match a role. Edit them under Users.
        </p>
      )}
    </>
  );
}

function AddUserDialog({
  catalog,
  held,
  close,
  onLinked,
}: {
  catalog: Catalog;
  held: string[] | null;
  close: () => void;
  onLinked: (message: string | null) => void;
}) {
  const client = useQueryClient();
  const [displayName, setDisplayName] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [access, setAccess] = useState(() => defaultAccess(catalog, held));
  const preset = catalog.presets.find((item) => item.id === access);
  const role = catalog.roles.find((item) => item.id === access);
  const create = useMutation({
    mutationFn: async () => {
      const created = result(
        await api.POST("/api/auth/users", {
          body: {
            display_name: displayName.trim(),
            username: username.trim(),
            password,
            role:
              preset && presetRoles.has(preset.id as PresetRole)
                ? (preset.id as PresetRole)
                : "member",
            ...(role ? { permissions: role.permissions } : {}),
          },
        }),
      );
      if (!role) return null;
      try {
        result(
          await api.PUT("/api/auth/users/{user_id}/permissions", {
            params: { path: { user_id: created.id } },
            body: {
              permissions: role.permissions,
              role_id: role.id,
              expected_permissions: created.permissions,
            },
          }),
        );
      } catch {
        return `${created.display_name} was added, but ${role.name} was not assigned. Edit them and choose that role again.`;
      }
      return null;
    },
    onSuccess: (message) => {
      client.invalidateQueries({ queryKey: ["accounts"] });
      onLinked(message);
      close();
    },
  });
  return (
    <BookDialog title="Add user" close={close} className="access-dialog">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          create.mutate();
        }}
      >
        <div className="form-row">
          <label>
            Name
            <input
              value={displayName}
              required
              maxLength={120}
              autoFocus
              autoComplete="name"
              onChange={(event) => setDisplayName(event.target.value)}
            />
          </label>
          <label>
            Username
            <input
              value={username}
              required
              minLength={3}
              maxLength={100}
              autoComplete="off"
              onChange={(event) => setUsername(event.target.value)}
            />
          </label>
        </div>
        <div className="form-row">
          <label>
            Password
            <input
              value={password}
              type="password"
              required
              minLength={12}
              maxLength={256}
              autoComplete="new-password"
              onChange={(event) => setPassword(event.target.value)}
            />
            <small>At least 12 characters.</small>
          </label>
          <label>
            Role
            <AccessSelect
              catalog={catalog}
              held={held}
              value={access}
              onChange={setAccess}
            />
          </label>
        </div>
        <p className="access-hint">
          {role?.description || preset?.description}
        </p>
        <Notice error={create.error} />
        <div className="access-form-actions">
          <button type="button" onClick={close}>
            Cancel
          </button>
          <button className="primary" disabled={create.isPending}>
            {create.isPending ? "Adding…" : "Add user"}
          </button>
        </div>
      </form>
    </BookDialog>
  );
}

function EditUserDialog({
  user,
  catalog,
  held,
  selfId,
  close,
}: {
  user: User;
  catalog: Catalog;
  held: string[] | null;
  selfId?: string;
  close: () => void;
}) {
  const client = useQueryClient();
  const [selected, setSelected] = useState(user.permissions);
  const [roleId, setRoleId] = useState<string | null>(
    user.permission_role_id ?? null,
  );
  const key = roleId ?? presetKey(catalog, selected) ?? "";
  const preset = catalog.presets.find((item) => `preset:${item.id}` === key);
  const role = catalog.roles.find((item) => item.id === roleId);
  const save = useMutation({
    mutationFn: async () =>
      result(
        await api.PUT("/api/auth/users/{user_id}/permissions", {
          params: { path: { user_id: user.id } },
          body: {
            permissions: selected,
            role_id: roleId,
            expected_permissions: user.permissions,
          },
        }),
      ),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["accounts"] });
      if (user.id === selfId)
        client.invalidateQueries({ queryKey: ["session"] });
      close();
    },
  });
  return (
    <BookDialog
      title={`Edit ${user.display_name}`}
      close={close}
      className="access-dialog access-dialog-wide"
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate();
        }}
      >
        <label>
          Role
          <select
            value={key}
            autoFocus
            onChange={(event) => {
              const value = event.target.value;
              if (value.startsWith("preset:")) {
                const next = catalog.presets.find(
                  (item) => item.id === value.slice("preset:".length),
                );
                setRoleId(null);
                setSelected(next?.permissions ?? []);
                return;
              }
              const next = catalog.roles.find((item) => item.id === value);
              setRoleId(value || null);
              if (next) setSelected(next.permissions);
            }}
          >
            {key === "" && <option value="">Custom</option>}
            <optgroup label="Built-in">
              {catalog.presets.map((item) => (
                <option
                  key={item.id}
                  value={`preset:${item.id}`}
                  disabled={
                    !canGrant(held, item.permissions, user.permissions) &&
                    key !== `preset:${item.id}`
                  }
                >
                  {item.label}
                </option>
              ))}
            </optgroup>
            {!!catalog.roles.length && (
              <optgroup label="Custom">
                {catalog.roles.map((item) => (
                  <option
                    key={item.id}
                    value={item.id}
                    disabled={
                      !canGrant(held, item.permissions, user.permissions) &&
                      roleId !== item.id
                    }
                  >
                    {item.name}
                  </option>
                ))}
              </optgroup>
            )}
          </select>
        </label>
        <p className="access-hint">
          {role?.description ||
            preset?.description ||
            "These permissions apply only to this person."}
        </p>
        <PermissionChecks
          catalog={catalog}
          held={held}
          baseline={user.permissions}
          selected={selected}
          onChange={(next) => {
            setRoleId(null);
            setSelected(next);
          }}
        />
        <Notice error={save.error} />
        <div className="access-form-actions">
          <button type="button" onClick={close}>
            Cancel
          </button>
          <button
            className="primary"
            disabled={save.isPending || (!selected.length && key === "")}
          >
            {save.isPending ? "Saving…" : "Save changes"}
          </button>
        </div>
      </form>
    </BookDialog>
  );
}

function RoleDialog({
  role,
  catalog,
  held,
  close,
  onSaved,
}: {
  role: Role | null;
  catalog: Catalog;
  held: string[] | null;
  close: () => void;
  onSaved: () => void;
}) {
  const client = useQueryClient();
  const [name, setName] = useState(role?.name ?? "");
  const [description, setDescription] = useState(role?.description ?? "");
  const [selected, setSelected] = useState(
    role?.permissions ??
      ["request", "request_ebook", "request_audio"].filter((name) =>
        canGrant(held, [name]),
      ),
  );
  const [confirming, setConfirming] = useState(false);
  const save = useMutation({
    mutationFn: async () => {
      const body = {
        name: name.trim(),
        description: description.trim(),
        permissions: selected,
      };
      if (!role) return result(await api.POST("/api/auth/roles", { body }));
      return result(
        await api.PUT("/api/auth/roles/{role_id}", {
          params: { path: { role_id: role.id } },
          body,
        }),
      );
    },
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["access-catalog"] });
      onSaved();
      close();
    },
  });
  const remove = useMutation({
    mutationFn: async () => {
      if (!role) return;
      result(
        await api.DELETE("/api/auth/roles/{role_id}", {
          params: { path: { role_id: role.id } },
        }),
      );
    },
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["access-catalog"] });
      onSaved();
      close();
    },
  });
  return (
    <BookDialog
      title={role ? `Edit ${role.name}` : "New role"}
      close={close}
      className="access-dialog access-dialog-wide"
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate();
        }}
      >
        <div className="form-row">
          <label>
            Role name
            <input
              value={name}
              required
              maxLength={80}
              autoFocus
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <label>
            Description
            <input
              value={description}
              maxLength={300}
              onChange={(event) => setDescription(event.target.value)}
            />
          </label>
        </div>
        <PermissionChecks
          catalog={catalog}
          held={held}
          baseline={role?.permissions ?? []}
          selected={selected}
          onChange={setSelected}
        />
        {!selected.length && (
          <p className="access-hint">Choose at least one permission.</p>
        )}
        <Notice error={save.error || remove.error} />
        {confirming && role ? (
          <div className="access-confirm">
            <p>
              Delete {role.name}? People who use it keep the permissions they
              have now.
            </p>
            <div className="access-form-actions">
              <button type="button" onClick={() => setConfirming(false)}>
                Keep role
              </button>
              <button
                type="button"
                className="danger"
                disabled={remove.isPending}
                onClick={() => remove.mutate()}
              >
                {remove.isPending ? "Deleting…" : "Delete role"}
              </button>
            </div>
          </div>
        ) : (
          <div className="access-form-actions">
            {role && (
              <button
                type="button"
                className="access-delete"
                onClick={() => setConfirming(true)}
              >
                Delete role
              </button>
            )}
            <button type="button" onClick={close}>
              Cancel
            </button>
            <button
              className="primary"
              disabled={save.isPending || !name.trim() || !selected.length}
            >
              {save.isPending
                ? "Saving…"
                : role
                  ? "Save changes"
                  : "Create role"}
            </button>
          </div>
        )}
      </form>
    </BookDialog>
  );
}

function AccessSelect({
  catalog,
  held,
  value,
  onChange,
}: {
  catalog: Catalog;
  held: string[] | null;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <select value={value} onChange={(event) => onChange(event.target.value)}>
      <optgroup label="Built-in">
        {catalog.presets.map((preset) => (
          <option
            key={preset.id}
            value={preset.id}
            disabled={
              !canGrant(held, preset.permissions) && value !== preset.id
            }
          >
            {preset.label}
          </option>
        ))}
      </optgroup>
      {!!catalog.roles.length && (
        <optgroup label="Custom">
          {catalog.roles.map((role) => (
            <option
              key={role.id}
              value={role.id}
              disabled={!canGrant(held, role.permissions) && value !== role.id}
            >
              {role.name}
            </option>
          ))}
        </optgroup>
      )}
    </select>
  );
}

function PermissionChecks({
  catalog,
  held,
  baseline,
  selected,
  onChange,
}: {
  catalog: Catalog;
  held: string[] | null;
  baseline: string[];
  selected: string[];
  onChange: (next: string[]) => void;
}) {
  const admin = selected.includes("admin");
  const groups = [...new Set(catalog.permissions.map((item) => item.group))];
  const allowed = (name: string) =>
    held === null || held.includes(name) || baseline.includes(name);
  return (
    <div className="permission-grid">
      {groups.map((group) => (
        <fieldset key={group}>
          <legend>{group}</legend>
          {catalog.permissions
            .filter((item) => item.group === group)
            .map((item) => (
              <label key={item.name}>
                <input
                  type="checkbox"
                  checked={admin || selected.includes(item.name)}
                  disabled={
                    (admin && item.name !== "admin") ||
                    (held !== null && item.name === "admin") ||
                    !allowed(item.name)
                  }
                  onChange={() =>
                    onChange(
                      togglePermission(selected, item.name, catalog, allowed),
                    )
                  }
                />
                <span>
                  {item.label}
                  <small>{item.description}</small>
                </span>
              </label>
            ))}
        </fieldset>
      ))}
    </div>
  );
}

const requestMedia = ["request_ebook", "request_audio"];
const autoMedia = ["auto_approve_ebook", "auto_approve_audio"];

function togglePermission(
  selected: string[],
  name: string,
  catalog: Catalog,
  allowed: (name: string) => boolean,
) {
  if (name === "admin") {
    return selected.includes("admin")
      ? selected.filter((value) => value !== "admin")
      : catalog.permissions.map((permission) => permission.name);
  }
  const has = selected.includes(name);
  let next = has
    ? selected.filter((value) => value !== name)
    : [...selected, name];
  if (name === "request" && has)
    next = next.filter((value) => !requestMedia.includes(value));
  if (
    requestMedia.includes(name) &&
    !has &&
    !next.includes("request") &&
    allowed("request")
  )
    next = [...next, "request"];
  if (name === "auto_approve" && !has) {
    for (const bit of autoMedia)
      if (!next.includes(bit) && allowed(bit)) next.push(bit);
  }
  if (name === "auto_approve" && has)
    next = next.filter((value) => !autoMedia.includes(value));
  if (autoMedia.includes(name) && has)
    next = next.filter((value) => value !== "auto_approve");
  return next;
}

function canGrant(
  held: string[] | null,
  permissions: string[],
  baseline: string[] = [],
) {
  if (held === null) return true;
  return permissions.every(
    (name) => held.includes(name) || baseline.includes(name),
  );
}

function defaultAccess(catalog: Catalog, held: string[] | null) {
  const presets = catalog.presets.filter((preset) =>
    canGrant(held, preset.permissions),
  );
  return (
    presets.find((preset) => preset.id === "member")?.id ??
    presets[0]?.id ??
    "viewer"
  );
}

function same(left: string[], right: string[]) {
  if (left.length !== right.length) return false;
  const values = new Set(left);
  return right.every((item) => values.has(item));
}

const automateOptional = new Set(["member", "approver", "requester"]);

function matchesPreset(
  preset: { id: string; permissions: string[] },
  selected: string[],
) {
  if (same(preset.permissions, selected)) return true;
  if (!automateOptional.has(preset.id) || !selected.includes("automate"))
    return false;
  return same(
    preset.permissions,
    selected.filter((name) => name !== "automate"),
  );
}

function presetKey(catalog: Catalog, selected: string[]) {
  const match = catalog.presets.find((preset) =>
    matchesPreset(preset, selected),
  );
  return match ? `preset:${match.id}` : null;
}

function presetPeople(people: User[], label: string) {
  return people.filter(
    (user) => !user.permission_role_id && user.access_label === label,
  ).length;
}

function rolePeople(people: User[], id: string) {
  return people.filter((user) => user.permission_role_id === id).length;
}

function countLabel(count: number) {
  return count === 1 ? "1 person" : `${count} people`;
}
