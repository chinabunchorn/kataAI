# Infrastructure Specification — Sandboxed AI Code Execution Platform

**Project:** Sandboxed AI Code Execution Using Kata Containers  
**Document version:** 0.3.0
**Last updated:** 2026-11-11  
**Environment:** Development / University Course Laboratory  
**Milestone:** M1 — Kubernetes and Kata Containers Infrastructure  
**Status:** M1 feasibility acceptance Verified — trusted correlated execution, non-root I/O, tested network isolation, Windows operations and cleanup recorded; production hardening remains Pending

---

## 1. Purpose

This document records the infrastructure architecture, environment specifications, networking, security configuration, software components, and verification results for the Sandboxed AI Code Execution Platform.

The project develops an AI agent capable of generating Python programs in response to user requests and executing them inside disposable, isolated virtual machines using Kata Containers.

The system uses Kubernetes to orchestrate sandbox workloads and OpenStack to provide the underlying Linux virtual machine infrastructure.

This document serves as:

- A single source of truth for infrastructure configuration.
- A reference for team members deploying and managing the environment.
- A record of verified configuration and unresolved decisions.
- Supporting evidence for the virtualization course project.
- A foundation for reproducible installation and troubleshooting procedures.

### 1.1 Configuration status conventions

| Status | Meaning |
|---|---|
| Verified | Confirmed through actual configuration or command output |
| Confirmed | Agreed project decision, not necessarily deployed |
| Planned | Proposed configuration awaiting implementation |
| Pending | Requires investigation or an explicit decision |
| Blocked | Cannot proceed without a decision or environment change |
| Failed | Tested but did not meet the required condition |

**Rule:** Proposed configuration must not be marked as verified until it has been implemented and tested.

---

## 2. System Architecture

### 2.1 High-level architecture

The platform separates trusted application components from the isolated code execution infrastructure.

```mermaid
flowchart TB
    subgraph LOCAL["Local Development Machine"]
        UI["Web Frontend"]
        API["FastAPI Backend"]
        LLM["llama.cpp Inference Server"]
        STORE["Local Application Storage"]

        UI <--> API
        API <--> LLM
        API <--> STORE
    end

    subgraph CLOUD["OpenStack Infrastructure"]
        subgraph HOST["Ubuntu VM — katavm"]
            K8S["Kubernetes"]
            CRI["containerd"]
            KATA["Kata Containers Runtime"]

            K8S --> CRI
            CRI --> KATA

            subgraph GUEST["Disposable Kata VM"]
                RUNNER["Python Runner"]
                DATA["Authorized Input Data"]
            end

            KATA --> GUEST
        end
    end

    API <-->|"Secure Kubernetes API Connection"| K8S
```

### 2.2 Component placement

| Component | Deployment location | Status |
|---|---|---|
| Web frontend | Local Windows PC | Confirmed |
| FastAPI backend | Local Windows PC | Confirmed |
| llama.cpp inference server | Local Windows PC | Confirmed |
| LLM model | Local Windows PC | Pending selection |
| Application and dataset storage | Local Windows PC | Confirmed location; technology pending |
| Kubernetes control plane | OpenStack Ubuntu VM | Verified |
| Kubernetes worker | Same OpenStack VM | Verified |
| containerd | OpenStack Ubuntu VM | Verified |
| Kata Containers | OpenStack Ubuntu VM | Verified |
| Python execution workload | Disposable Kata VM | Verified with trusted fixture |

The initial implementation uses a single-node Kubernetes cluster where the control plane and worker share the same OpenStack VM.

The LLM and FastAPI backend do not run inside Kata Containers.

**All model-generated Python must execute inside an approved Kata sandbox. The system must never fall back to executing generated code on the local development machine.**

---

## 3. OpenStack Infrastructure

### 3.1 Virtual machine specifications

**Instance hostname:** `katavm`

| Property | Value | Status |
|---|---|---|
| Cloud platform | OpenStack | Verified |
| Hostname | `katavm` | Verified |
| Operating system | Ubuntu 24.04.3 LTS | Verified |
| OS codename | Noble Numbat | Verified |
| Architecture | x86_64 | Verified |
| Virtual CPUs | 4 | Verified |
| Total memory | 7.8 GiB | Verified |
| Virtual disk | 24 GB | Verified |
| Root filesystem | `/dev/vda1` | Verified |
| Root filesystem size | 23 GB | Verified |
| Initial available storage | Approximately 21 GB | Verified |
| Latest available storage | Approximately 14 GB | Verified 2026-11-11 |
| Latest disk utilization | 42% | Verified 2026-11-11 |
| Swap | Disabled (0 B) | Verified |
| Virtualization platform | KVM | Verified |
| SSH login account | `ubuntu` | Verified |
| OpenStack flavor name | Not recorded | Pending |
| OpenStack compute host | Not recorded | Pending |
| Root disk backing type | Instance-local or Cinder volume | Pending |

### 3.2 Disk layout

Output from `lsblk`:

```text
NAME      SIZE  TYPE  MOUNTPOINTS
vda        24G  disk
├─vda1     23G  part  /
├─vda14     4M  part
├─vda15   106M  part  /boot/efi
└─vda16   913M  part  /boot
```

Initial filesystem usage:

```text
Filesystem  Size  Used  Avail  Use%
/dev/vda1    23G  1.9G    21G    9%
```

Latest recorded filesystem usage, after Kubernetes, Calico, and Kata installation:

```text
Filesystem  Size  Used  Avail  Use%  Mounted on
/dev/vda1    23G  9.2G    14G   42%  /
```

### 3.3 Storage strategy

The initial VM had approximately 21 GB available, sufficient to begin the single-node Kubernetes and Kata feasibility experiments.

After installation and infrastructure testing, approximately 14 GB remains available.

The project will initially avoid resizing the disk unless installation or workload testing demonstrates insufficient capacity.

Proposed operational thresholds:

| Available capacity | Action |
|---|---|
| Greater than 8 GB | Continue normally |
| 5–8 GB | Review disk usage and container image storage |
| Less than 5 GB | Stop adding workloads; clean unused resources or expand storage |

These thresholds are project guidelines rather than Kubernetes defaults.

Monitor storage using:

```bash
df -h /
df -i /
```

After containerd and Kubernetes installation:

```bash
sudo du -sh \
  /var/lib/containerd \
  /var/lib/kubelet \
  /opt/kata 2>/dev/null
```

Do not manually delete runtime-managed files from containerd or kubelet directories.

---

## 4. Virtualization Capabilities

### 4.1 CPU virtualization support

The VM exposes Intel virtualization extensions.

Verification command:

```bash
grep -E -o '(vmx|svm)' /proc/cpuinfo | sort -u
```

Observed output:

```text
vmx
```

### 4.2 KVM availability

Verification:

```bash
ls -l /dev/kvm
```

Observed output:

```text
crw-rw---- 1 root kvm 10, 232 /dev/kvm
```

Host virtualization detection:

```bash
systemd-detect-virt
```

Observed output:

```text
kvm
```

KVM capability check:

```bash
sudo kvm-ok
```

Observed output:

```text
INFO: /dev/kvm exists
KVM acceleration can be used
```

**Status: Verified — nested Kata VM execution successful.**

A Kata-backed Pod successfully launched a QEMU/KVM guest VM.

Verification evidence:

- Host kernel: `6.8.0-71-generic`
- Kata guest kernel: `6.18.56`
- Hypervisor binary: `/opt/kata/bin/qemu-system-x86_64`
- QEMU version: `11.0.1 (kata-static)`
- Hardware acceleration: `accel=kvm`
- Guest vCPU configuration: 1 vCPU
- Guest initial memory configuration: 2 GiB
- Pod deletion terminated the corresponding QEMU process.

The successful nested VM execution confirms that the OpenStack environment supports the selected Kata/QEMU workload.

### 4.3 Required kernel modules

The following modules were loaded successfully:

| Module | Purpose | Status |
|---|---|---|
| `kvm` | Linux KVM virtualization infrastructure | Verified |
| `kvm_intel` | Intel-specific KVM support | Verified |
| `vhost_vsock` | Host–guest communication support | Verified |
| `vhost_net` | Virtual networking acceleration | Verified |
| `overlay` | Overlay filesystem support | Verified |
| `br_netfilter` | Bridge traffic filtering | Verified |

The device `/dev/vhost-vsock` was verified to exist.

Persistent module loading has been configured:

File: `/etc/modules-load.d/kata-containers.conf`

```text
vhost_vsock
vhost_net
```

File: `/etc/modules-load.d/k8s.conf`

```text
overlay
br_netfilter
```

**Status:** Configuration files created; persistence after a VM reboot has not yet been separately tested.

---

## 5. OpenStack Networking

### 5.1 Current network configuration

| Property | Value | Status |
|---|---|---|
| Network interface | `ens3` | Verified |
| Private IPv4 | `10.77.10.138` | Verified |
| Private subnet | `10.77.10.0/24` | Verified |
| Default gateway | `10.77.10.1` | Verified |
| Network MTU | 1450 | Verified |
| IP assignment | DHCP | Verified |
| DHCP server address observed | `10.77.10.100` | Verified |
| OpenStack metadata endpoint | `169.254.169.254` | Verified route |
| SSH-reachable external address | `172.31.1.57` | Verified connection |
| Floating IP association | Exact Neutron configuration not recorded | Pending |
| OpenStack network name | `kata-network` | Planned name; verify in Horizon |
| Subnet name | `kata-subnet` | Planned name; verify in Horizon |
| Router name | `kata-router` | Planned name; verify in Horizon |
| Security group name | `kata-k8s-sg` | Planned name; verify in Horizon |

The private IPv4 address is assigned using DHCP and may change. Long-term references should not depend on the address remaining constant.

### 5.2 Observed network routes

```text
default via 10.77.10.1 dev ens3

10.77.10.0/24 dev ens3

10.77.10.1 dev ens3

10.77.10.100 dev ens3

169.254.169.254 via 10.77.10.100 dev ens3
```

### 5.3 Network architecture

```mermaid
flowchart TB
    LAPTOP["Local Development Machine"]
    EXT["University External Network"]
    ROUTER["OpenStack Neutron Router"]
    SUBNET["Private Subnet: 10.77.10.0/24"]
    VM["katavm: 10.77.10.138"]

    LAPTOP <-->|"SSH / Private Access"| EXT
    EXT <--> ROUTER
    ROUTER <--> SUBNET
    SUBNET <--> VM
```

The external connection may use a Floating IP, VPN, or another approved access mechanism.

SSH connectivity was verified using `172.31.1.57`. The complete Floating IP association and router resource identifiers have not yet been recorded.

### 5.4 Network security principles

- Restrict external SSH access to authorized users and network ranges.
- Do not publicly expose the Kubernetes API.
- Do not expose the local llama.cpp service publicly.
- Separate the trusted application network from sandbox workload permissions.
- Restrict sandbox networking independently of the OpenStack VM's networking.
- Never place application credentials inside Kata workloads.

---

## 6. Kubernetes Network Planning

Kubernetes introduces virtual Pod and Service networks separate from the OpenStack subnet.

### 6.1 Cluster network ranges

The actual network ranges were retrieved from the Kubernetes `kubeadm-config` ConfigMap.

| Network | CIDR / Address | Status |
|---|---|---|
| OpenStack subnet | `10.77.10.0/24` | Verified |
| Kubernetes Pod CIDR | `10.244.0.0/16` | Verified |
| Kubernetes Service CIDR | `10.96.0.0/12` | Verified |
| Kubernetes node IP | `10.77.10.138` | Verified; DHCP |
| DNS Service IP | `10.96.0.10` | Verified |
| Kubernetes DNS domain | `cluster.local` | Verified |

Configuration source:

```bash
kubectl -n kube-system get cm kubeadm-config \
  -o jsonpath='{.data.ClusterConfiguration}'
```

Relevant configuration:

```yaml
networking:
  dnsDomain: cluster.local
  podSubnet: 10.244.0.0/16
  serviceSubnet: 10.96.0.0/12
```

The actual Pod and Service CIDRs do not overlap the routes observed on `katavm`.

Overlaps with any additional university or VPN networks have not been independently audited.

### 6.2 Network MTU

Observed OpenStack interface MTU:

```text
ens3: 1450
```

Installed CNI: Calico.

The Calico node image was verified as:

```text
quay.io/calico/node:v3.33.0
```

The Tigera Operator reported:

- Calico: Available, not progressing, not degraded.
- IP pools: Available, not progressing, not degraded.
- Tiers: Available, not progressing, not degraded.

The Kubernetes node reached `Ready`, and both CoreDNS Pods were operational.

If Calico uses IPv4 VXLAN encapsulation over this interface, a candidate workload MTU is approximately 1400 bytes.

Current inspection verified MTU 1400 in Installation status and `ip -o link show vxlan.calico`. Larger-packet/path-MTU traffic tests remain Pending.

### 6.3 Kubernetes topology

The MVP uses:

- One Kubernetes control-plane node.
- One Kubernetes worker role on the same machine.
- One authorized sandbox execution workload at a time.
- No high-availability control plane.
- No multi-node scheduling requirement.

This topology is intended for a course laboratory, not production hosting.

**Status: Single-node Kubernetes topology verified operational.**

---

## 7. Ports and Communication

The following table defines the expected communication paths and exposure policy.

**This is not a complete audit of currently open firewall ports.**

### 7.1 Application and infrastructure ports

| Service | Port / protocol | Source → Destination | Exposure | Status |
|---|---|---|---|---|
| SSH | TCP 22 | Authorized laptops → OpenStack VM | Restricted | In use |
| Kubernetes API | TCP 6443 | Windows PC → Kubernetes through SSH tunnel | Private | Verified |
| etcd client | TCP 2379–2380 | Kubernetes control-plane components | Internal only | etcd running; exposure not audited |
| Kubelet API | TCP 10250 | Authorized control-plane components → kubelet | Internal only | kubelet operational; exposure not audited |
| kube-scheduler | TCP 10259 | Local control-plane management | Internal only | Component running |
| kube-controller-manager | TCP 10257 | Local control-plane management | Internal only | Component running |
| HTTPS downloads | TCP 443 | VM → package registries | Outbound | Verified for selected endpoints |
| HTTP downloads | TCP 80 | VM → approved endpoints, if required | Outbound | Pending |
| DNS | UDP/TCP 53 | VM → configured DNS resolvers | Required outbound | DNS resolution verified |
| Calico VXLAN | UDP 4789 | Kubernetes node-to-node traffic | Internal only, if applicable | CNI operational; exposure not audited |

Additional ports must be documented if required by the selected CNI configuration.

### 7.2 Local application ports

| Component | Port | Binding policy |
|---|---|---|
| FastAPI | Pending | Localhost by default |
| Frontend development server | Pending | Localhost by default |
| llama.cpp HTTP server | Pending | Localhost by default |
| Local Kubernetes API tunnel | TCP 16443 | `127.0.0.1` on Windows PC; verified |

Do not assume that common development ports are the final project configuration.

### 7.3 Kubernetes API access from the local development machine

The Windows development PC successfully established an SSH tunnel to the Kubernetes API running on `katavm`.

Verified connection:

- Remote SSH endpoint: `172.31.1.57:22`
- Kubernetes API endpoint on the VM: `127.0.0.1:6443`
- Windows local tunnel endpoint: `127.0.0.1:16443`
- API version returned: `v1.37.2`
- Kubernetes CA certificate copied to Windows
- TLS certificate validation succeeded
- Restricted Kubernetes ServiceAccount authenticated successfully

Verified tunnel command:

```powershell
ssh -N -L 127.0.0.1:16443:127.0.0.1:6443 ubuntu@172.31.1.57
```

Verified HTTPS request:

```powershell
curl.exe --ssl-revoke-best-effort `
  --cacert "$env:USERPROFILE\.kube\katavm-ca.crt" `
  https://127.0.0.1:16443/version
```

The `--ssl-revoke-best-effort` option was required because Windows Schannel could not obtain certificate revocation information.

It does not disable certificate-chain or hostname verification.

Conceptual route:

```text
Local FastAPI
    |
    | Kubernetes client (authenticated HTTPS)
    v
Local SSH Tunnel
    |
    | SSH
    v
OpenStack Ubuntu VM
    |
    | Kubernetes API
    v
Kubernetes Control Plane
```

A dedicated read-only ServiceAccount was verified for initial remote access.

Production-style credential separation is required even for the course demonstration:

- The application must not use unrestricted cluster-admin credentials.
- A dedicated Kubernetes identity must be used.
- Permissions must be limited to the required resources and namespace.
- Kubernetes credentials and SSH private keys must not be committed to Git.

The final execution-service identity and credential renewal mechanism remain pending.

---

## 8. Kernel Network Configuration

The following kernel configuration has been applied and verified.

File: `/etc/sysctl.d/99-kubernetes.conf`

```ini
net.bridge.bridge-nf-call-iptables = 1
net.ipv4.ip_forward = 1
```

Verification:

```bash
sysctl net.ipv4.ip_forward
sysctl net.bridge.bridge-nf-call-iptables
```

Observed output:

```text
net.ipv4.ip_forward = 1
net.bridge.bridge-nf-call-iptables = 1
```

Both required kernel modules are loaded:

```bash
lsmod | grep -E 'overlay|br_netfilter'
```

**Status: Verified.**

Swap was also confirmed disabled:

```text
Swap: 0B
```

---

## 9. Internet Connectivity

Basic external connectivity was tested before beginning software installation.

### 9.1 Docker package repository

Command:

```bash
curl -I --max-time 10 https://download.docker.com
```

Result:

```text
HTTP/2 200
```

**Status: Verified.**

### 9.2 Kubernetes domain

Command:

```bash
curl -I --max-time 10 https://pkgs.k8s.io
```

Result:

```text
HTTP/2 302
```

**Status: Verified — DNS and HTTPS connectivity to the domain.**

The response was an HTTP redirect.

Subsequent successful installation of containerd and Kubernetes packages confirmed that the required package downloads were accessible during setup.

---

## 10. Software Stack

### 10.1 Installed infrastructure software

| Component | Version / implementation | Status |
|---|---|---|
| Ubuntu Server | 24.04.3 LTS | Verified |
| Host kernel | `6.8.0-71-generic` | Verified |
| KVM | Intel KVM | Verified |
| containerd | 2.4.2 | Verified |
| Kubernetes | 1.37.2 | Verified |
| kubeadm | 1.37.2 | Verified |
| kubelet | 1.37.2 | Verified |
| kubectl | 1.37.2 | Verified |
| Calico node image | `quay.io/calico/node:v3.33.0` | Verified |
| Helm | `v4.3.1+gc0d08d0` | Verified |
| Kata Containers | 4.3.1; Helm chart `kata-deploy-4.3.1`, app 4.3.1, revision 1 | Verified 2026-11-11 |
| Kata runtime | `kata-qemu-runtime-rs` | Verified |
| Hypervisor | QEMU/KVM | Verified |
| QEMU | `11.0.1 (kata-static)` | Verified |
| Kata guest kernel | `6.18.56` | Verified |

The earlier Helm output-format issue was resolved with `helm list -n kata-system -o json`: release `kata-deploy`, status `deployed`, chart `kata-deploy-4.3.1`, app version `4.3.1`, revision `1`.

The Kata runtime itself was successfully registered and tested. The RuntimeClass was verified by inspecting a running Pod.

Host-side QEMU process inspection confirmed nested virtualization using KVM acceleration.

### 10.2 Local application stack

| Component | Technology | Status |
|---|---|---|
| Backend | Python FastAPI | Confirmed |
| Frontend | Web application | Confirmed |
| Frontend framework | Not selected | Pending |
| Model inference runtime | llama.cpp | Confirmed |
| LLM model | Not selected | Pending |
| Application storage | Local | Confirmed location |
| Storage implementation | Not selected | Pending |
| Kubernetes integration | Kubernetes Python client | Proposed |
| Data execution language | Python | Confirmed |
| Runner result format | Bounded JSON | Confirmed |

---

## 11. Kata Execution Architecture

### 11.1 Execution lifecycle

```mermaid
sequenceDiagram
    participant User
    participant API as Local FastAPI
    participant LLM as Local llama.cpp
    participant K8S as Kubernetes API
    participant Kata as Kata Sandbox

    User->>API: Submit question and inputs
    API->>LLM: Request Python generation
    LLM-->>API: Proposed Python code
    API->>API: Validate tool arguments
    API->>K8S: Stage inputs and create Kata Job
    K8S->>Kata: Start isolated guest VM
    Kata->>Kata: Execute generated Python
    Kata-->>K8S: Exit status and JSON result
    K8S-->>API: Execution outcome
    API->>API: Validate and persist result
    API->>K8S: Request workload cleanup
    API->>LLM: Send validated result
    LLM-->>API: Final explanation
    API-->>User: Answer and execution status
```

This is the target full application workflow. The underlying Kata execution and input/output feasibility have been demonstrated, but model orchestration and FastAPI integration have not yet been implemented.

### 11.2 Execution requirements

Every model-generated program must:

1. Be dispatched through the trusted execution service.
2. Execute using an approved Kata RuntimeClass.
3. Receive only explicitly authorized inputs.
4. Run without application or Kubernetes administrative credentials.
5. Respect configured CPU, memory, storage, output, and timeout limits.
6. Return a bounded structured result.
7. Have its execution outcome recorded.
8. Be cleaned up after execution or flagged if teardown cannot be confirmed.

The application must fail closed when Kata is unavailable.

### 11.3 Data transport

The precise production input and output transport mechanisms have not been selected.

Candidate approaches include:

- Run-specific Kubernetes ConfigMaps for small trusted fixtures.
- Approved read-only volumes for input staging.
- Kubernetes termination messages for small JSON results.
- A separately managed bounded artifact channel for larger outputs.

These approaches must be tested on the actual Kata configuration before being finalized.

### 11.4 M1 Input/Output Feasibility Result

A trusted Kubernetes Job using `kata-qemu-runtime-rs` successfully executed a Python script with a staged synthetic CSV.

The test used a ConfigMap to supply the script and dataset through a read-only volume mount.

Expected structured result:

```json
{
  "product": "Notebook",
  "october_units": 120,
  "november_units": 80,
  "change_units": -40
}
```

The retrieved output matched the expected JSON.

**Status: Verified for the trusted fixture.**

This demonstrates the feasibility of staging input files and retrieving structured results through Kubernetes.

The final production input/output transport, automated schema validation, output limits, and durable artifact handling remain undecided.

---

## 12. Security Requirements

### 12.1 Trust boundaries

The platform treats the following as untrusted:

- User prompts.
- Uploaded files.
- AI-generated Python code.
- Data returned by the sandbox.
- Text contained in tool outputs.

The trusted components include:

- Application authorization and validation logic.
- Execution service configuration.
- Kubernetes control plane.
- Approved runtime and infrastructure configuration.
- Authorized infrastructure operators.

Kata provides a guest-kernel isolation boundary, but the security of the host, hypervisor, runtime, and file-sharing mechanisms must still be evaluated.

### 12.2 Sandbox restrictions

| Control | Requirement | Status |
|---|---|---|
| Kata execution | Required for generated Python | Verified for trusted workloads |
| Dedicated namespace | Isolate execution resources | `kata-lab` created |
| Kubernetes RBAC | Restrict execution-service permissions | Read-only ServiceAccount verified; write permissions pending |
| Restricted Pod security | Reject privileged configurations | Planned |
| Non-root process | Required for runner | Tested in diagnostic Pod; general enforcement pending |
| No privilege escalation | Required | Tested in diagnostic Pod; general enforcement pending |
| No application credentials | Required | Planned |
| No Kubernetes API token | Disable automatic token mounting | Verified in test manifests; enforcement pending |
| Read-only inputs | Required | Verified in trusted fixture |
| Network restriction | Deny unapproved access | Default-deny tests passed; comprehensive hardening pending |
| CPU and memory limits | Required | Test limits used; final values pending |
| Execution deadline | Required | Configured in trusted Job; timeout behavior not verified |
| Output size limit | Required | Pending |
| Resource cleanup | Required | Kata Pod/VM teardown verified; full reconciliation pending |

NetworkPolicy enforcement was tested with Calico and the Kata runtime.

The initial controlled Pod-to-Service test succeeded before applying default-deny policy and timed out afterward.

Additional TCP probes against the Kubernetes API, OpenStack metadata endpoint, and public internet also timed out.

Default-deny NetworkPolicy alone is not sufficient proof that every sensitive node-local network path is inaccessible.

### 12.3 Secret management

Do not commit:

- SSH private keys.
- User passwords.
- Kubernetes administrator kubeconfig files.
- Service account credentials.
- API keys.
- Model-provider credentials.
- Tokens or secret-bearing environment files.

Document credential locations and access procedures without recording secret values.

### 12.4 Multi-user infrastructure administration

The MVP supports one application user, but multiple team members may administer the OpenStack VM.

Recommended access arrangement:

- Separate Linux accounts for each administrator.
- Individual SSH credentials.
- Restricted SSH ingress rules.
- Explicit sudo permissions.
- No shared private SSH keys.

Application-user authentication and infrastructure administrator access are separate concerns.

---

## 13. Milestone 1 Installation Record

This section is updated as installation proceeds.

### 13.1 Progress

| Stage | Description | Status |
|---|---|---|
| M1.1 | Provision Linux VM | Verified |
| M1.2 | Verify KVM capabilities | Verified |
| M1.3 | Configure kernel networking | Verified |
| M1.4 | Verify outbound connectivity | Verified |
| M1.5 | Install containerd | Verified — 2.4.2 |
| M1.6 | Install Kubernetes | Verified — 1.37.2 |
| M1.7 | Install Calico | Verified — node image v3.33.0 |
| M1.8 | Verify normal Kubernetes Pod | Passed |
| M1.9 | Install Kata Containers | Verified operational |
| M1.10 | Launch Kata-backed Pod | Passed |
| M1.11 | Verify guest VM identity and teardown | Passed |
| M1.12 | Verify trusted input/output transfer | Passed |
| M1.13 | Verify basic workload network restrictions | Passed |
| M1.14 | Verify secure remote API access | Passed |
| M1.15 | Verify restricted Kubernetes authentication | Passed |
| M1.16 | Verify fail-closed runtime selection | Passed for unavailable handler |
| M1.17 | Record final versions and infrastructure evidence | In progress |

### 13.2 Installation version record

| Component | Installed version | Configuration location | Verification |
|---|---|---|---|
| containerd | 2.4.2 | `/etc/containerd/config.toml` | Service active; CRI healthy; systemd cgroups enabled |
| kubeadm | 1.37.2 | `/etc/kubernetes/` | Verified |
| kubelet | 1.37.2 | `/var/lib/kubelet/` | Node Ready |
| kubectl | 1.37.2 | User kubeconfig | Verified |
| Calico node | v3.33.0 | Kubernetes DaemonSet | Image tag and operator health verified |
| Helm | v4.3.1 | Helm CLI / release metadata | Verified |
| Kata | 4.3.1; chart kata-deploy-4.3.1, revision 1 | `/opt/kata/` and containerd integration | Helm JSON metadata and correlated VM execution verified |
| QEMU | 11.0.1 (kata-static) | `/opt/kata/bin/qemu-system-x86_64` | Verified |
| Kata guest kernel | 6.18.56 | `/opt/kata/share/kata-containers/` | Verified |

### 13.3 Cluster verification commands

```bash
kubectl get nodes -o wide

kubectl get pods -A

kubectl get runtimeclasses

kubectl get jobs -A

kubectl get events -A \
  --sort-by=.metadata.creationTimestamp
```

### 13.4 Container runtime verification

```bash
containerd --version

sudo systemctl status containerd

sudo ctr plugins ls | grep cri
```

### 13.5 Kata verification

The team must record:

- The RuntimeClass selected by the Job.
- Successful creation of the Kata sandbox.
- The guest kernel version.
- The corresponding Pod UID.
- The node-side VM/hypervisor process.
- The workload's execution result.
- Confirmation of VM teardown.

The presence of a RuntimeClass alone is insufficient proof of VM-backed execution.

### 13.6 Kata Guest VM Verification

**Date:** 2026-11-11  
**Status:** PASSED

Test Pod: `kata-test`

Pod UID:

`0f0ca484-4230-4af5-9ba0-271be0804b97`

Selected RuntimeClass:

`kata-qemu-runtime-rs`

Host kernel:

`6.8.0-71-generic`

Guest kernel:

`6.18.56`

Observed QEMU process:

- PID: `19873`
- Binary: `/opt/kata/bin/qemu-system-x86_64`
- Version: `11.0.1 (kata-static)` (verified subsequently)
- Machine: `q35`
- Acceleration: `kvm`
- vCPU configuration: 1
- Initial memory: 2 GiB
- Guest kernel image: `vmlinux-6.18.56-208`

The Pod's guest kernel differed from the Ubuntu host kernel.

The running QEMU process confirmed that Kata launched a nested virtual machine.

Following `kubectl delete pod kata-test --wait=true`, the corresponding QEMU process was no longer present.

**Conclusion:** Nested Kata VM creation, execution, and process teardown were successfully demonstrated.

### 13.7 Trusted Python Execution

**Date:** 2026-11-11  
**Status:** PASSED

Test Job: `kata-csv-test`

RuntimeClass: `kata-qemu-runtime-rs`

Inputs:

- `data.csv`
- `script.py`

Input staging: Kubernetes ConfigMap mounted at `/inputs`.

The Python script calculated the largest absolute sales drop from October to November.

Expected result:

```json
{
  "product": "Notebook",
  "october_units": 120,
  "november_units": 80,
  "change_units": -40
}
```

The observed result matched the expected JSON.

**Conclusion:** Kubernetes successfully executed a trusted Python program inside Kata with staged CSV input and returned a structured result.

This test does not establish production output-size enforcement or full cleanup reconciliation.

### 13.8 Network Isolation Verification

**Date:** 2026-11-11  
**Status:** PASSED for tested destinations

Namespace: `kata-lab`

NetworkPolicy: `default-deny`

#### Pod-to-Service connectivity

Controlled destination:

`10.97.64.178:8080`

Before applying NetworkPolicy:

```text
reachable
```

After applying default-deny NetworkPolicy:

```text
wget: download timed out
command terminated with exit code 1
```

#### Sensitive network endpoint probes

| Destination | Address / port | Observed result |
|---|---|---|
| Kubernetes API Service | Service ClusterIP:443 | Timeout |
| Kubernetes node API | 10.77.10.138:6443 | Timeout |
| OpenStack metadata | 169.254.169.254:80 | Timeout |
| Public internet | 1.1.1.1:443 | Timeout |

All four TCP connection attempts failed with `TimeoutError`.

**Conclusion:** Network restrictions were effective against the tested endpoints.

**Limitation:** These results do not prove that every network path is blocked or establish which specific enforcement layer caused each timeout.

Additional security testing remains necessary before executing untrusted AI-generated programs.

### 13.9 Remote Kubernetes Access

**Date:** 2026-11-11  
**Status:** PASSED

Development environment: Windows PC

Remote infrastructure: OpenStack `katavm`

Verified connection:

```text
Windows localhost:16443
        |
        | SSH tunnel
        v
OpenStack katavm
        |
        v
Kubernetes API localhost:6443
```

The remote SSH endpoint used during testing was `172.31.1.57`.

The Kubernetes API returned version `v1.37.2` through the tunnel.

The Kubernetes CA certificate was transferred to Windows.

TLS validation succeeded using:

```powershell
curl.exe --ssl-revoke-best-effort `
  --cacert "$env:USERPROFILE\.kube\katavm-ca.crt" `
  https://127.0.0.1:16443/version
```

#### Kubernetes authentication

Namespace: `kata-lab`

ServiceAccount: `kata-client-readonly`

Role: `kata-client-reader`

RoleBinding: `kata-client-reader-binding`

Verified authorization:

| Operation | Result |
|---|---|
| List Pods | Allowed |
| Read Jobs | Allowed |
| Create Jobs | Denied |
| Delete Pods | Denied |

A temporary ServiceAccount token authenticated successfully from Windows.

**Conclusion:** Remote Kubernetes connectivity, TLS certificate validation, ServiceAccount authentication, and namespace-scoped read-only RBAC were verified.

The application still requires a suitable long-term credential lifecycle and restricted execution permissions.

### 13.10 Fail-Closed Runtime Verification

**Date:** 2026-11-11  
**Status:** PASSED

Test configuration:

- RuntimeClass: `kata-unavailable-test`
- Handler: `kata-handler-not-installed`
- Namespace: `kata-lab`
- Pod: `kata-failclosed-test`

Observed behavior:

1. Kubernetes accepted and scheduled the Pod.
2. kubelet attempted to create the Pod sandbox.
3. containerd could not find the requested runtime handler.
4. Sandbox creation failed.
5. The Pod remained unready with no container ID.

Observed error:

```text
FailedCreatePodSandBox:
no runtime for "kata-handler-not-installed" is configured
```

No successful execution or fallback to the default `runc` runtime was observed.

**Conclusion:** Kubernetes/containerd failed closed for an unavailable runtime handler.

**Limitation:** Failure of an actual configured Kata runtime after handler selection has not yet been tested.

---

## 14. Operational Procedures

### 14.1 Check VM resources

```bash
hostname
uptime
free -h
df -h /
df -i /
nproc
```

### 14.2 Check virtualization support

```bash
sudo kvm-ok

ls -l /dev/kvm

ls -l /dev/vhost-vsock

lsmod | grep -E 'kvm|vhost'
```

### 14.3 Check network connectivity

```bash
ip -4 addr

ip -4 route

hostname -I

getent hosts pkgs.k8s.io
```

### 14.4 Check Kubernetes health

After installation:

```bash
kubectl get nodes

kubectl get pods -A

kubectl cluster-info
```

### 14.5 Check containerd

After installation:

```bash
sudo systemctl status containerd

sudo journalctl -u containerd -n 100 --no-pager
```

### 14.6 Check kubelet

After installation:

```bash
sudo systemctl status kubelet

sudo journalctl -u kubelet -n 100 --no-pager
```

### 14.7 Reboot verification

After the infrastructure is installed, reboot testing should confirm:

- Kernel modules reload correctly.
- Containerd starts successfully.
- Kubernetes services recover.
- The node returns to `Ready`.
- Kata RuntimeClass remains available.
- A new trusted Kata workload can start.
- No orphaned workloads remain from the pre-reboot state.

---

## 15. Open Decisions

| ID | Decision | Current position |
|---|---|---|
| D01 | OpenStack root disk capacity | Retain 24 GB initially; 14 GB currently available |
| D02 | Exact Kubernetes patch version | 1.37.2 verified |
| D03 | Exact containerd version | 2.4.2 verified |
| D04 | Calico version and configuration | Node image v3.33.0 verified; exact effective network configuration partially pending |
| D05 | Final Pod CIDR | `10.244.0.0/16` verified |
| D06 | Final Service CIDR | `10.96.0.0/12` verified |
| D07 | Final Calico MTU | Verified 1400 in Installation status and vxlan.calico interface |
| D08 | Kata Containers release | Verified 4.3.1; Helm chart kata-deploy-4.3.1, app 4.3.1, revision 1 |
| D09 | Input staging strategy | ConfigMap tested successfully; final approach pending |
| D10 | Result collection mechanism | JSON output retrieved; final mechanism pending |
| D11 | Runner resource limits | Pending |
| D12 | Sandbox network restrictions | Calico default-deny tests passed; complete security policy pending |
| D13 | Remote Kubernetes API access | Windows SSH tunnel and TLS verified |
| D14 | Kubernetes application identity and RBAC | Temporary operator-only Windows write test verified and identity deleted; persistent application admission/credentials Pending |
| D15 | LLM model | Pending |
| D16 | Frontend framework | Pending |
| D17 | Local application data storage | Pending |
| D18 | Optional Kata versus runc benchmark | Deferred |

Decisions must be recorded with their rationale and verification evidence when finalized.

---

## 16. Milestone 1 Acceptance Criteria

The master roadmap's seven M1 feasibility acceptance criteria now have supporting evidence. The component checklist below is supporting evidence, not an alternative milestone gate. Historical unavailable-handler evidence is retained with its narrow scope; current execution/health/Windows/cleanup evidence is in §16.5. Additional hardening, reboot recovery, production credential lifecycle, output enforcement, and independent reproduction remain Pending follow-up checks, not silently added M1 exit criteria. This does not authorize model-generated execution or imply M6 readiness.

### 16.1 Roadmap audit and execution plan (2026-11-11)

Use **Verified** only for observed evidence, **Pending** for untested requirements, and **Blocked** for a required decision or environment change. Partial evidence is described explicitly under Pending.

| Task | Status | Evidence and remaining work |
|---|---|---|
| M1-T01 OpenStack feasibility | Verified | Current SSH, usable KVM, CPU/RAM/disk and nested QEMU observed; flavor/compute-host inventory remains Pending administrative metadata. |
| M1-T02 Runtime integration | Verified | Exact release/chart, handler, effective containerd integration and current health inspected (§16.5). |
| M1-T03 Basic Job | Verified | Both runs used the checked-in one-completion/parallelism-one, restartPolicy Never, backoffLimit-zero template. |
| M1-T04 VM proof | Verified | Job/Pod owner UIDs, sandbox labels, container SandboxID, shim ID and QEMU parent/name correlated (§16.5). |
| M1-T05 I/O feasibility | Verified | UID/GID 10001, actual denied input writes, absent token file and canonical JSON observed under unchanged default-deny. This is the selected M1 test user, not a frozen production runner contract. |
| M1-T06 Network feasibility | Verified for tested paths | Clean TCP API/kubelet/metadata/internet/DNS/controlled peer and UDP DNS probes timed out; broader path/host isolation remains Pending before M6. |
| M1-T07 Fail-closed | Verified historically for unavailable handler | The deliberately unconfigured handler visibly failed sandbox creation without an executing container. This meets the unavailable-handler spike scope, not every configured-runtime failure mode. |
| M1-T08 Teardown | Verified | Both Jobs/Pods/ConfigMaps and guest processes removed; first deletion sequence measured one second; transient sandbox metadata residue later disappeared (§16.5). |
| M1-T09 Risk disposition | Verified for feasibility | Smallest tested setup, mount/log channel, exact versions and unresolved limits/security risks recorded (§16.5). |
| M1-T10 Windows API operations | Verified for operator spike | Actual Windows curl/SSH workflow used verified TLS and a separate 600-second identity; created/read/deleted trusted resources; identity rolled back (§16.5). |

**Access:** Initial direct SSH authentication failed; the user enabled key access and supplied alias `katavm`. BatchMode alias access as `ubuntu` is now Verified. No private keys/admin kubeconfigs were read, printed or copied. When the user introduced a stricter approval requirement during the first run, further mutations paused until exact cleanup and temporary Windows RBAC/test/cleanup were separately approved. No services were restarted, packages installed or runtime/network policies changed.

**Execution order:** (1) read-only host/cluster inventory; (2) select an already available Python image by observed digest and verify existing default-deny; (3) create only one uniquely named ConfigMap and trusted Kata Job; (4) capture live UID/sandbox/QEMU/kernel evidence and validate result/exit status; (5) delete only that execution's resources, measure disappearance and inspect residue; (6) separately review temporary Windows execution identity permissions before applying them; (7) update evidence and check only fully satisfied roadmap criteria.

### 16.2 Reproducible test assets and evidence requirements

Verified test assets are in `tests/infrastructure/m1/`: `inspect.sh` (read-only inventory), canonical `data.csv`, `trusted_csv.py`, `network-probes.py`, `job.template.yaml`, `windows-test-rbac.yaml` and `windows-test.ps1`. Do not run the Python fixtures on Windows, the Ubuntu host or runc. Do not apply the template with unresolved placeholders. Future mutations require approval under the user's current operating rule.

The template proposes UID/GID 10001, one CPU/256 MiB container limits, 64 MiB ephemeral-storage limit, 16 MiB scratch, a 180-second Job deadline, disabled token automount, read-only root and input mounts, no added capabilities and no privilege escalation. These are M1 test values; effective Kata VM overhead and actual enforcement must be recorded separately. A 60-second trusted observation delay allows live VM correlation. It does not prove cancellation/timeout enforcement. The fixture emits bounded canonical JSON and diagnostic UID/kernel facts, but does not implement a production output protocol.

For future approved reruns, copy these trusted files to a new run-specific remote directory, run `bash inspect.sh`, then use the following sequence with a unique `run` name and an **observed digest-pinned Python image**. Stop if the existing namespace or required deny policy is absent, or admission rejects the security settings; do not relax policy.

```bash
# On katavm, from the staged test directory. Proposed commands; not observed output.
run="m1-csv-$(date -u +%Y%m%d%H%M%S)"
# Set image to a verified, available Python repository@sha256:digest. No invented digest.
test -n "${image:?Set observed Python image digest first}"
kubectl -n kata-lab get networkpolicy default-deny -o yaml
kubectl -n kata-lab get networkpolicy -o yaml
kubectl create configmap "$run-inputs" -n kata-lab \
  --from-file=data.csv --from-file=trusted_csv.py
sed -e "s/RUN_NAME/$run/g" -e "s|PYTHON_IMAGE_DIGEST|$image|g" \
  job.template.yaml > "$run.yaml"
kubectl create -f "$run.yaml"
kubectl -n kata-lab get job "$run" -o yaml
kubectl -n kata-lab get pods -l "kataai-m1-run=$run" -o yaml
# Capture while the fixture is running, before the 60-second observation delay ends:
sudo -n ctr -n k8s.io sandboxes ls
# crictl is absent. Select sandbox by exact Pod UID from metadata, then:
# sudo -n ctr -n k8s.io sandboxes info "$sandbox" | jq '{ID,Labels,Runtime:.Runtime.Name}'
# sudo -n ctr -n k8s.io containers info "$container" | jq '{ID,Labels,SandboxID,Runtime:.Runtime.Name}'
# Inspect the exact associated shim and QEMU command lines/PIDs. Record the
# sandbox ID linkage, /opt/kata/bin/qemu-system-x86_64 and accel=kvm.
# Mere simultaneous QEMU presence does not establish the relationship.
kubectl -n kata-lab logs "job/$run"
kubectl -n kata-lab wait --for=condition=complete "job/$run" --timeout=200s
kubectl -n kata-lab get pods -l "kataai-m1-run=$run" -o yaml
# Validate the sole expected JSON and terminated exitCode=0 before cleanup.
# Record timestamps and exact QEMU PID/start time before/after deletion.
date -Is
kubectl -n kata-lab delete job "$run" --cascade=foreground --wait=true --timeout=90s
kubectl -n kata-lab delete configmap "$run-inputs" --wait=true
date -Is
kubectl -n kata-lab get job "$run" --ignore-not-found
kubectl -n kata-lab get pods -l "kataai-m1-run=$run"
kubectl -n kata-lab get configmap "$run-inputs" --ignore-not-found
# Reinspect CRI sandboxes and exact correlated QEMU PID/start time; record
# whether teardown already occurred at completion, or after deletion.
```

Inventory for each run: one Job `$run`, its controller-created Pod(s), one ConfigMap `$run-inputs`, their exact UIDs, and the local/remote staging files. Record resources immediately after successful creation, including during partial failures. No broad delete or deletion of historical test resources is authorized. If a command fails, inspect and clean only this inventory; do not silently leave staging or report success. Kubernetes Events, completed CRI records and retained logs may persist after object deletion; distinguish expected retained metadata from a live orphan VM or mount.

### 16.3 Windows submission proposal — approval required before RBAC changes

**Verified supervised test:** Used the loopback-only SSH tunnel with TLS hostname/CA verification and temporary operator-only ServiceAccount/Role/RoleBinding `m1-client-20261111`. Preserved `kata-client-readonly`. Exact approved rules in `windows-test-rbac.yaml`: create Jobs/ConfigMaps; get/delete only named `m1-win-20261111` Job and its input ConfigMap; get/list Pods and get pods/log in `kata-lab`. No Pod creation/exec, Secrets, RBAC mutation, impersonation or cluster-wide access. Listing refers to the dedicated namespace's Pods, not cluster Namespace enumeration. No persistent application write identity remains.

**Blocked for untrusted/persistent application submission:** Even these permissions allow arbitrary Job templates and cannot constrain RuntimeClass, host mounts or ServiceAccount choice. Approval covered only the short supervised **trusted operator** test, with no application/model access to the token. A production/untrusted submitter requires admission or enforced server-owned workload templates before write credentials are granted. RBAC alone is insufficient ([Kubernetes authorization](https://kubernetes.io/docs/reference/access-authn-authz/authorization/), [RBAC good practices](https://kubernetes.io/docs/concepts/security/rbac-good-practices/)).

Before applying changes, present the exact temporary identity names, Role rules, exposure window and rollback commands for approval. Request a ten-minute TokenRequest credential, inspect its granted expiry privately (the API may adjust the requested duration), hold it only in Windows process memory, and authenticate HTTPS requests without printing headers, command-line tokens, kubeconfigs or credential responses. Delete the RoleBinding/Role/ServiceAccount immediately after the test, including on failure. No Secret-based persistent token or cluster-admin kubeconfig transfer is needed ([TokenRequest instructions](https://kubernetes.io/docs/tasks/configure-pod-container/configure-service-account/)).

The proposed change could allow unsafe workloads in `kata-lab` if the credential is misused during its lifetime. Rollback removes only the newly created binding, Role and ServiceAccount plus the test's exact Job/ConfigMap; it preserves the existing reader. Do not apply it without approval. Public API exposure and actual OpenStack security-group restrictions remain Pending inspection; using a private tunnel alone does not prove port 6443 is unreachable from every public network.

### 16.4 Roadmap acceptance status

| Roadmap criterion | Status |
|---|---|
| Canonical computation inside verified Kata VM | Verified, both correlated runs |
| Job/Pod UID → VM and observed termination | Verified, both runs (§16.5) |
| I/O with selected UID and network restrictions | Verified, UID/GID 10001 under default-deny |
| Required paths denied or explicit blockers recorded | Verified for enumerated paths; broader security/host isolation remains Pending before M6 |
| Unavailable Kata fails without alternate execution | Verified historically for unavailable handler only; current rerun Pending |
| Selected versions and compatibility questions recorded | Verified current matrix and compatibility/limits questions (§16.5) |
| Secure Windows submit/inspect/delete | Verified actual Windows HTTPS operations; temporary identity removed |

Roadmap checkboxes are updated only for the seven supported feasibility criteria. Reboot/recovery and failure injection into the working runtime were not performed and are not required to repeat the unavailable-handler spike. Completing M1 does not waive M6/M8 gates before model-generated execution.

### 16.5 Observed M1 evidence — 2026-11-11

All timestamps below are UTC (Bangkok = UTC+7); the inspection interval 09:25–09:34 UTC corresponds to 16:25–16:34 Bangkok. Values are observations, not illustrative outputs.

**Current infrastructure — Verified**

| Item | Observation |
|---|---|
| Host/user | `katavm` / `ubuntu`, UID 1000; SSH alias `katavm` with BatchMode succeeds |
| OS/host kernel | Ubuntu 24.04.3 LTS / `6.8.0-71-generic` |
| CPU/RAM | 4 vCPUs; 7.8 GiB total, 1.5 GiB used, 6.3 GiB available at 09:25:40 UTC; swap 0 B |
| Root filesystem | `/dev/vda1`, 23G, 9.2G used, 14G available, 42%; inodes 4% used |
| KVM | `vmx`, `/dev/kvm`, `kvm-ok`: acceleration usable; required modules loaded; forwarding/bridge sysctls both 1 |
| Kubernetes | API, kubectl, kubeadm, kubelet all `v1.37.2`; node Ready, internal IP `10.77.10.138`; all API readyz checks passed |
| Control plane/CNI/DNS | etcd, API server, scheduler, controller manager, kube-proxy, CoreDNS and Calico Pods healthy, zero recorded restarts; final node still Ready |
| containerd | `v2.4.2`, commit `b7a25261e029d68978bbf290df0a62fc819b3c51`; containerd/kubelet active; CRI runtime/images/grpc plugins `ok` |
| Effective Kata integration | handler `kata-qemu-runtime-rs`, runtime type `io.containerd.kata-qemu-runtime-rs.v2`, path `/opt/kata/runtime-rs/bin/containerd-shim-kata-v2`; snippet `/etc/containerd/conf.d/kata-deploy.toml` |
| Kata configuration | `/opt/kata/share/defaults/kata-containers/runtime-rs/runtimes/qemu-runtime-rs/configuration-qemu-runtime-rs.toml` |
| RuntimeClass | same name/handler; fixed overhead CPU 250m, memory 320Mi; Kata node selectors present |
| Kata/Helm | release `kata-deploy`, namespace `kata-system`, chart `kata-deploy-4.3.1`, app `4.3.1`, revision 1, deployed; Helm CLI `v4.3.1+gc0d08d0` |
| QEMU/guest kernel | `11.0.1 (kata-static)` / `6.18.56`, guest image kernel `vmlinux-6.18.56-208` |
| Calico | node `quay.io/calico/node:v3.33.0`, operator image `quay.io/tigera/operator:v1.44.0`; Available=True, Progressing=False, Degraded=False |
| CNI mode | BGP Disabled, VXLAN, Iptables dataplane, NAT outgoing enabled, pool `10.244.0.0/16`; Installation MTU and vxlan.calico MTU 1400 |
| Cluster networking | Pod CIDR `10.244.0.0/16`, Service CIDR `10.96.0.0/12`, DNS `10.96.0.10`, domain `cluster.local` |
| Applicable policy | `kata-lab/default-deny`, UID `4da3eb78-8193-4f2b-85c6-3f52df396063`, selector `{}`, Ingress/Egress, no allow rules; no additional Kubernetes policy there; no global Calico or cluster network policy objects found |
| Initial leftovers | No Jobs/Pods/input ConfigMaps in kata-lab; only kube-root-ca.crt, default/read-only SAs and existing reader Role/binding |

The base containerd file alone did not show Kata; `sudo -n containerd config dump` showed the effective imported handler. It emitted a configuration-migration warning; no migration was attempted. Default runtime is runc for ordinary cluster components; both test Jobs explicitly requested and demonstrably used Kata. `crictl` is not installed; existing `ctr` inspection was sufficient. Calico APIs are `projectcalico.org/v3`; initial `crd.projectcalico.org` queries failed and were corrected. `kata-system` had release metadata but no current DaemonSet/Deployment; this did not prevent installed runtime execution. No component was reinstalled or upgraded.

**Trusted execution — Verified**

Both runs used `job.template.yaml` and the exact canonical CSV/script in the test directory, image `docker.io/library/python@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b` (already cached as Python 3.12-slim). Input was a run-specific ConfigMap. The expected result, observed in both runs and independently parsed/checked by the Windows script in the second, was:

```json
{"product":"Notebook","october_units":120,"november_units":80,"change_units":-40}
```

Both emitted:

```json
{"uid":10001,"gid":10001,"guest_kernel":"6.18.56","input_write_denied":true,"serviceaccount_token_absent":true}
```

The fixture asserted UID 10001, attempted opening the mounted CSV for append and observed denial, and checked the token path was absent. Kubernetes also reported UID/GID 10001 and `/inputs` readOnly=true. Both Jobs completed with container exitCode=0 and no restart. This is evidence for these actual mounts/user settings, not general admission enforcement.

| Correlation | First SSH-submitted run | Windows HTTPS-submitted run |
|---|---|---|
| Job | `m1-csv-20261111-0926` | `m1-win-20261111` |
| Job UID | `efd77347-0777-4c86-a96d-1febde6af803` | `cee0f679-5fd4-43f9-983c-d1b058a2bf09` |
| Pod | `m1-csv-20261111-0926-6zv9l` | `m1-win-20261111-rrzcm` |
| Pod UID | `c8521701-f27a-4f69-a285-35b8f57c18b1` | `1db0d9c3-dab6-4a09-8406-9e800ad6b7a0` |
| Container ID | `071c48c87b040ffcc177aaf913c2c3059cb76ac6471bd6a4cfa7204aa17a3579` | `f7f7e5e5e929fea781dde24a9b682a2e66e27fe6d1127704759a2acc66b9d2b0` |
| Sandbox ID | `418184fb8d4a43e6400fb0cf44da6bc04a4e3381ca5b1bfa9e69e9e6bf82ade9` | `fe85d620744f7f07fd6c3716fa7ef15faec5a23039ac44e5c84f77ca61a7b01c` |
| Kata shim PID → QEMU PID | `41832` → `41849` | `44220` → `44237` |
| QEMU identity | `-name sandbox-418184fb…` | `-name sandbox-fe85d620…` |
| QEMU configuration | `q35,accel=kvm`, `-smp 2`, `-m 288M` | `q35,accel=kvm`, `-smp 2`, `-m 288M` |
| Input ConfigMap | `m1-csv-20261111-0926-inputs` | `m1-win-20261111-inputs`, UID `94262f44-c85b-4370-b2e5-89c8b8af3a90` |

Pod controller ownerReferences matched the Job UIDs. `ctr ... sandboxes info` labels matched Job UID, Pod UID/name/namespace and Kata runtime type; first-run `ctr ... containers info` additionally showed the exact SandboxID. Each shim's `-id` and its QEMU child's `-name sandbox-<full-ID>` matched that sandbox, with QEMU binary `/opt/kata/bin/qemu-system-x86_64`, `accel=kvm` and the guest kernel path. This establishes the chain independently of the RuntimeClass field.

First Pod container started `09:26:50Z`, finished `09:27:50Z`, exit 0/Completed; Job reported 73-second duration including scheduling/startup. QEMU/shim were present at `09:27:44Z` and absent by `09:28:16Z` before deletion. The observed shutdown window is at most 26 seconds after workload finish; exact VM-exit timestamp was not sampled. RuntimeClass overhead resulted in reported Pod limits CPU 1250m, memory 576Mi, versus container CPU 1/memory 256Mi; QEMU initial memory was 288M. These are distinct accounting layers, not a stress test proving CPU/RAM/disk limits.

**Network probes — Verified for enumerated paths**

The clean `network-probes.py` execution inside the Windows-created Kata Pod exited 0 and reported `TimeoutError` for every destination below, with a two-second socket timeout per probe. Reproduction while the trusted guest is running (on katavm, with the trusted probe file staged and `$pod` set to the exact observed Pod):

```bash
kubectl -n kata-lab exec -i "$pod" -- python3 -I - < network-probes.py
```

| Protocol | Destination | Purpose |
|---|---|---|
| TCP | `10.96.0.1:443` | Kubernetes API Service |
| TCP | `10.77.10.138:6443` | Node API |
| TCP | `10.77.10.138:10250` | Sensitive kubelet endpoint |
| TCP | `169.254.169.254:80` | OpenStack metadata |
| TCP | `1.1.1.1:443` | Public IP |
| TCP and UDP | `10.96.0.10:53` | DNS Service; UDP sent a bounded A query for kubernetes.default.svc.cluster.local |
| TCP | `10.244.253.3:53` | Observed running CoreDNS peer |

The previous controlled HTTP Service before/after-policy test (§13.8) remains the positive reachability control. No policy was relaxed. Current peer/DNS timeout results alone do not identify the enforcement layer or prove all network paths blocked. Other node ports, IPv6, alternate interfaces/protocols and host escape resistance remain Pending security work before M6. The first six-probe invocation printed timeouts but ended with a CRLF-induced `NameError`; only the later clean exit-zero invocation is treated as the reproducible probe run.

**Windows API operations — Verified**

After explicit approval, created the exact temporary SA/Role/binding in `windows-test-rbac.yaml`. `windows-test.ps1 -Approved` ran on Windows, not Ubuntu. It used `ssh -N -L 127.0.0.1:16443:127.0.0.1:6443 katavm`, `curl.exe --ssl-revoke-best-effort --cacert <existing-user-CA-path>` and HTTPS `https://127.0.0.1:16443`. Certificate verification was never disabled. The token was requested over SSH, captured only into process memory, granted exactly 600 seconds, and supplied to curl over stdin configuration rather than arguments/files. No token contents or admin kubeconfig were printed/copied/committed.

Observed API version `v1.37.2`; namespace Pod listing allowed; HTTPS POST ConfigMap and POST Job succeeded; GET Job polling and GET Pod/log succeeded; expected result/UID controls/owner UID/runtime/exit 0 validated; HTTPS DELETE Job (foreground) and input ConfigMap accepted, dependent Pod absence polled. Independent SSH GETs with `--ignore-not-found` then returned no Job/ConfigMap, confirming deletion. Temporary binding/Role/SA were deleted; original read-only SA/Role/binding remained. The script-created SSH tunnel was stopped. No application/model was granted a persistent credential.

Exact operator steps used for this approved Windows spike (future reruns require renewed approval and collision-free names):

```powershell
Get-Content -Raw tests/infrastructure/m1/windows-test-rbac.yaml |
  ssh -o BatchMode=yes katavm 'kubectl create -f -'
& ./tests/infrastructure/m1/windows-test.ps1 -Approved
# Always remove the temporary identity, including when the client script fails:
ssh -o BatchMode=yes katavm 'kubectl -n kata-lab delete rolebinding m1-client-20261111'
ssh -o BatchMode=yes katavm 'kubectl -n kata-lab delete role m1-client-20261111'
ssh -o BatchMode=yes katavm 'kubectl -n kata-lab delete serviceaccount m1-client-20261111'
```

Direct Windows TCP probe to `172.31.1.57:6443` timed out after three seconds. Host listeners are `*:6443` and `*:10250`; the secure workflow needed no new public exposure. **Pending:** full Neutron/security-group ingress audit; a single client timeout does not prove global public unreachability. No firewall/API binding was changed.

**Cleanup — Verified with bounded residue observations**

First cleanup was approved after the updated user restriction. At `09:29:19Z`, deleted only Job `m1-csv-20261111-0926` with foreground cascading deletion and ConfigMap `m1-csv-20261111-0926-inputs`; at `09:29:20Z` the Job, Pod and ConfigMap were absent. The four observed files (`data.csv`, `trusted_csv.py`, `job.template.yaml`, `job.yaml`) and empty directory `/home/ubuntu/m1-codex-20261111-0926` were removed. The approval question had mistakenly said five files; inspection showed four and only those four were deleted. Measured cleanup was one second. Exact PIDs, `/run/kata/<sandbox-ID>` and `/var/lib/kubelet/pods/<Pod-UID>` were absent. A stopped sandbox metadata record initially remained; it was absent by the second run's inspection. No manual runtime-state removal occurred.

Second cleanup used the approved Windows DELETE workflow. By `09:33:12Z`, independent checks found no matching Job/Pod/ConfigMap, PIDs 44220/44237, Kata run directory or kubelet Pod directory. Temporary RBAC was then removed. Its stopped sandbox record initially remained but no Kata sandbox appeared in the later final inventory around `09:34Z`; no matching `/var/log/pods/kata-lab_m1-*` directory was found. Windows cleanup was bounded/polled to at most 60 seconds for Pod disappearance; exact DELETE-to-absence latency was not separately measured for this second run. Final namespace inventory contained only the original CA ConfigMap and default/read-only identities. No unrelated resources were deleted.

**Fail-closed assessment — Verified at the M1 spike scope**

The historical unavailable-handler test (§13.10) satisfies M1-T07's break/remove-handler alternative: explicit failed sandbox creation, no container ID, no executed script or observed runc fallback. It was not repeated or upgraded to a claim about every real runtime failure. No working handler/service was disrupted. A separate missing-RuntimeClass trusted Job would be a minimal reversible future negative (admission/controller failure, no Pod execution), but requires approval and adds no proof of a configured Kata crash. Stronger configured-runtime failure injection remains Pending and must be separately approved.

**Feasibility decision and remaining limits**

M1's seven roadmap criteria are supported by current correlated trusted execution, non-root read-only ConfigMap/log I/O under denial, explicit network probes, historical unavailable-handler failure, exact installed versions, measured teardown and actual Windows API operations. The smallest verified setup is one single-node cluster, one trusted Kata Job at a time, one tiny ConfigMap and Kubernetes logs; no FastAPI/LLM/frontend was added.

ConfigMaps/logs are candidate M1 channels only. The fixture bounds its own result to 1024 bytes; the Windows script validates the canonical result but does not implement generic untrusted output caps/schema/depth enforcement. Large datasets, mount alternatives, output truncation/retention, cancellation/failure/deadline teardown, stress-limit enforcement, long-term credentials and compatibility outside this exact tested stack remain Pending. Persistent untrusted Job creation is Blocked until template/admission enforcement is approved and verified. Reboot recovery and full installation reconstruction were not tested; no upgrade/reinstall was required. M1 completion does not authorize bypassing later security gates.

The following component checklist records narrower historical and current observations; it does not override the status table above.

### Infrastructure

- [x] Linux VM provisioned on OpenStack.
- [x] CPU virtualization extensions visible.
- [x] `/dev/kvm` present.
- [x] `kvm-ok` reports acceleration available.
- [x] Required networking and virtualization modules loaded.
- [x] IPv4 forwarding enabled.
- [x] Outbound DNS and HTTPS connectivity verified.
- [x] Kubernetes node reaches `Ready`.
- [x] Normal Kubernetes Pod executes successfully.

### Kata Containers

- [x] Compatible Kata runtime installed and operational.
- [x] Approved Kata RuntimeClass registered.
- [x] Kubernetes Job launches using Kata.
- [x] Node-side evidence confirms a real Kata guest VM.
- [x] Trusted Python fixture produces the expected result.
- [x] Authorized input can be staged and read inside Kata.
- [x] Structured JSON result retrieved and checked against expected output.
- [x] Kata VM process teardown verified after Pod deletion.
- [x] Complete Job and temporary staging-resource cleanup independently verified.
- [ ] Automated output-size and schema enforcement implemented.

### Security and connectivity

- [x] Unauthorized Job creation denied for the read-only ServiceAccount.
- [x] Basic network isolation verified for tested destinations.
- [x] Unavailable runtime handler fails without observed fallback.
- [x] Local development machine reaches Kubernetes through an SSH tunnel.
- [x] TLS certificate validation verified.
- [x] Namespace-scoped read-only authentication and RBAC verified.
- [ ] Long-term application credential lifecycle finalized.
- [ ] Complete sandbox security policy and admission enforcement verified.
- [ ] Real configured Kata runtime failure-injection test completed.

### Reproducibility

- [x] Exact versions of selected infrastructure components recorded.
- [x] Initial infrastructure configuration documented.
- [ ] Complete reproducible installation guide finalized.
- [x] Known limitations documented.
- [ ] Reboot and recovery tests completed.
- [ ] Another team member independently reproduces the trusted execution test.

---

## 17. Known Limitations

As of this document version:

1. A nested Kata/QEMU guest VM has been successfully launched, but reboot recovery and more advanced failure scenarios remain untested.
2. Kubernetes v1.37.2, containerd v2.4.2, Calico node image v3.33.0, Helm v4.3.1, QEMU 11.0.1 and Kata chart/app 4.3.1 are Verified for this stack; broader upgrade/version compatibility is Pending.
3. The VM has limited disk capacity, requiring storage monitoring. Approximately 14 GB was available at the latest inspection.
4. The OpenStack private IP is DHCP-assigned.
5. Remote SSH connectivity through `172.31.1.57` is verified, but the complete Neutron resource inventory has not been recorded.
6. The Kubernetes Pod and Service CIDRs and Calico VXLAN MTU 1400 are Verified; broader MTU/path testing remains Pending.
7. ConfigMap-based input staging and JSON output retrieval were tested using a trusted fixture. Final transport, limits, and cleanup reconciliation are not yet finalized.
8. Network isolation succeeded for tested endpoints. These tests do not establish complete protection against every network path or host-level attack.
9. Read-only authentication and temporary operator-only Windows Job operations are Verified. Application credential lifecycle and enforced workload admission remain Pending/Blocked before untrusted submission.
10. Fail-closed behavior was demonstrated for an unconfigured runtime handler, not for every possible Kata runtime failure.
11. The exact llama.cpp model and frontend implementation remain undecided.

These limitations must be revisited as the project progresses.

---

## 18. References

### OpenStack

- [OpenStack Documentation](https://docs.openstack.org/)
- [OpenStack Networking (Neutron)](https://docs.openstack.org/neutron/latest/)

### Kubernetes

- [Kubernetes Documentation](https://kubernetes.io/docs/)
- [Installing kubeadm](https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/install-kubeadm/)
- [Creating a Cluster with kubeadm](https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/create-cluster-kubeadm/)
- [Container Runtimes](https://kubernetes.io/docs/setup/production-environment/container-runtimes/)
- [Kubernetes RuntimeClass](https://kubernetes.io/docs/concepts/containers/runtime-class/)
- [Kubernetes Jobs](https://kubernetes.io/docs/concepts/workloads/controllers/job/)
- [Kubernetes NetworkPolicy](https://kubernetes.io/docs/concepts/services-networking/network-policies/)

### Kata Containers

- [Kata Containers Repository](https://github.com/kata-containers/kata-containers)
- [Kata Containers Installation Guide](https://github.com/kata-containers/kata-containers/blob/main/docs/installation.md)
- [Kata Containers Threat Model](https://github.com/kata-containers/kata-containers/blob/main/docs/threat-model/threat-model.md)

### Container Networking

- [Calico Documentation](https://docs.tigera.io/calico/latest/)
- [containerd Repository](https://github.com/containerd/containerd)

---

## 19. Document Change Log

| Version | Date | Description |
|---|---|---|
| 0.1.0 | 2026-11-11 | Initial infrastructure inventory, verified KVM/network findings, planned Kubernetes/Kata configuration, and M1 acceptance criteria |
| 0.2.0 | 2026-11-11 | Recorded Kubernetes/containerd installation, Calico readiness, Kata VM verification, trusted Python execution, network isolation, remote API authentication, and fail-closed runtime verification |
| 0.3.0 | 2026-11-11 | Audited roadmap; verified current stack/Kata chart, two correlated trusted non-root executions, clean network probes, approved Windows API workflow and cleanup; recorded exact evidence, transient residue and later security gates |

---

**Maintenance requirement:** Update this document whenever infrastructure configuration, network addressing, software versions, runtime policies, or verified capabilities change. Keep secrets and credential material outside version control.
