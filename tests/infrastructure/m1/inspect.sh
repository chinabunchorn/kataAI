#!/usr/bin/env bash
# Read-only inventory. Does not print kubeconfigs, Secrets or token-bearing logs.
set -u
section() { printf '\n### %s\n' "$1"; }
section 'Timestamp and host'
date -Is
hostname
id
cat /etc/os-release
uname -r
nproc
free -h
df -h /
df -i /
ls -l /dev/kvm /dev/vhost-vsock
grep -Eo 'vmx|svm' /proc/cpuinfo | sort -u
lsmod | grep -E 'kvm|vhost|overlay|br_netfilter'
sysctl net.ipv4.ip_forward net.bridge.bridge-nf-call-iptables
section 'Versions and services'
containerd --version
kubectl version -o yaml
kubeadm version -o short
kubelet --version
helm version --short
systemctl is-active containerd kubelet
sudo -n kvm-ok
sudo -n ctr plugins ls
sudo -n containerd config dump | grep -A20 -B4 kata
/opt/kata/bin/qemu-system-x86_64 --version
section 'Cluster and runtime health'
kubectl get nodes -o wide
kubectl get --raw='/readyz?verbose'
kubectl get pods -A -o wide
kubectl get runtimeclass -o yaml
kubectl -n kube-system get cm kubeadm-config -o jsonpath='{.data.ClusterConfiguration}'
section 'Kata release metadata (not Helm values or Secrets)'
helm list -A -o json
kubectl -n kata-system get daemonsets,deployments -o wide
section 'Calico configuration and policy'
kubectl get tigerastatus
kubectl -n calico-system get ds calico-node -o jsonpath='{.spec.template.spec.containers[*].image}'
kubectl get installations.operator.tigera.io default -o yaml
kubectl get ippools.projectcalico.org -o yaml
kubectl get felixconfigurations.projectcalico.org -o yaml
kubectl get globalnetworkpolicies.projectcalico.org -o yaml
kubectl get networkpolicies.projectcalico.org -A -o yaml
kubectl get networkpolicy -A -o yaml
section 'Sandbox inventory (no Secret contents)'
kubectl get namespace kata-lab --show-labels
kubectl -n kata-lab get jobs,pods,configmaps,serviceaccounts,roles,rolebindings -o wide
section 'Existing runtime sandboxes and VM processes'
sudo -n ctr -n k8s.io sandboxes ls
ps -eo pid,ppid,args | grep -E '[q]emu-system|[c]ontainerd-shim-kata'
