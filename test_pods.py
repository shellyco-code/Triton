import sys
sys.path.append(r'c:\Users\komal\OneDrive\Documents\Desktop\Triton')
from app.k8s.client import load_k8s, list_unhealthy_pods

load_k8s()
pods = list_unhealthy_pods(None)
print(f'\nTotal unhealthy pods found across ALL namespaces: {len(pods)}')

namespaces = set(p['namespace'] for p in pods)
print('Namespaces with unhealthy pods: ' + (str(namespaces) if namespaces else 'None'))

for pod in pods:
    print(f"- Namespace: {pod['namespace']} // Pod: {pod['name']} // Issues: {pod['issues']}")
