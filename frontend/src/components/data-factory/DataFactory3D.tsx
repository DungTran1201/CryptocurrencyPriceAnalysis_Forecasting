import React, { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { FACTORY_STATIONS, FACTORY_CONNECTIONS, StationInfo } from './dataFactoryTypes';

interface DataFactory3DProps {
  selectedStationId: string | null;
  onSelectStation: (station: StationInfo) => void;
  streamStatus: Record<string, any>;
  wsConnected: boolean;
  reducedMotion?: boolean;
}

export const DataFactory3D: React.FC<DataFactory3DProps> = ({
  selectedStationId,
  onSelectStation,
  streamStatus,
  wsConnected,
  reducedMotion = false
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  // Keep latest callbacks/props in refs for requestAnimationFrame loop
  const onSelectStationRef = useRef(onSelectStation);
  onSelectStationRef.current = onSelectStation;
  const streamStatusRef = useRef(streamStatus);
  streamStatusRef.current = streamStatus;
  const wsConnectedRef = useRef(wsConnected);
  wsConnectedRef.current = wsConnected;
  const reducedMotionRef = useRef(reducedMotion);
  reducedMotionRef.current = reducedMotion;
  const selectedStationIdRef = useRef(selectedStationId);
  selectedStationIdRef.current = selectedStationId;

  const [hoveredStation, setHoveredStation] = useState<StationInfo | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    const canvas = canvasRef.current;
    if (!container || !canvas) return;

    let width = container.clientWidth || 800;
    let height = container.clientHeight || 550;

    // 1. Scene setup
    const scene = new THREE.Scene();
    scene.background = new THREE.Color('#0B0E11');
    scene.fog = new THREE.FogExp2('#0B0E11', 0.015);

    // 2. Camera setup - Isometric perspective
    const camera = new THREE.PerspectiveCamera(40, width / height, 0.1, 1000);
    const initialCamPos = new THREE.Vector3(26, 26, 26);
    const targetLookAt = new THREE.Vector3(0, 0, 0);
    camera.position.copy(initialCamPos);
    camera.lookAt(targetLookAt);

    // 3. Renderer
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({
        canvas,
        antialias: true,
        alpha: false,
        powerPreference: 'high-performance'
      });
    } catch {
      // Fallback handled by parent if WebGL completely unsupported
      return;
    }

    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.1;

    // 4. Lighting
    const ambientLight = new THREE.AmbientLight('#334155', 1.8);
    scene.add(ambientLight);

    const dirLight = new THREE.DirectionalLight('#E2E8F0', 2.2);
    dirLight.position.set(20, 35, 15);
    scene.add(dirLight);

    // Secondary fill light (cool cyan)
    const fillLight = new THREE.DirectionalLight('#00D8FF', 0.9);
    fillLight.position.set(-20, 15, -15);
    scene.add(fillLight);

    // Hub accent point light (gold warm glow)
    const hubPointLight = new THREE.PointLight('#FCD535', 1.5, 30);
    hubPointLight.position.set(0, 4, -8);
    scene.add(hubPointLight);

    // 5. Floor Grid
    const gridHelper = new THREE.GridHelper(50, 50, '#1E293B', '#111827');
    gridHelper.position.y = -0.05;
    scene.add(gridHelper);

    // Subtle dark circular platform
    const platformGeo = new THREE.CylinderGeometry(28, 28, 0.1, 48);
    const platformMat = new THREE.MeshStandardMaterial({
      color: '#0D1117',
      roughness: 0.9,
      metalness: 0.1
    });
    const platform = new THREE.Mesh(platformGeo, platformMat);
    platform.position.y = -0.15;
    scene.add(platform);

    // 6. Build Stations
    const stationMeshes: { mesh: THREE.Group; info: StationInfo; coreMesh: THREE.Mesh }[] = [];
    const interactiveObjects: THREE.Object3D[] = [];

    FACTORY_STATIONS.forEach((info) => {
      const group = new THREE.Group();
      group.position.set(...info.position);

      // Station Base plinth
      const baseGeo = new THREE.BoxGeometry(info.size[0], 0.3, info.size[2]);
      const baseMat = new THREE.MeshStandardMaterial({
        color: '#161E27',
        roughness: 0.7,
        metalness: 0.3
      });
      const baseMesh = new THREE.Mesh(baseGeo, baseMat);
      baseMesh.position.y = 0.15;
      group.add(baseMesh);

      // Glowing trim ring on base
      const trimGeo = new THREE.BoxGeometry(info.size[0] + 0.1, 0.06, info.size[2] + 0.1);
      const trimMat = new THREE.MeshBasicMaterial({
        color: info.color,
        transparent: true,
        opacity: 0.6
      });
      const trimMesh = new THREE.Mesh(trimGeo, trimMat);
      trimMesh.position.y = 0.03;
      group.add(trimMesh);

      // Station Main Machinery Structure
      let coreGeo: THREE.BufferGeometry;
      if (info.category === 'BROKER') {
        // Cylindrical broker distributor
        coreGeo = new THREE.CylinderGeometry(info.size[0] * 0.45, info.size[0] * 0.45, info.size[1], 24);
      } else if (info.category === 'STORAGE') {
        // Multi-level warehouse vault
        coreGeo = new THREE.BoxGeometry(info.size[0] * 0.85, info.size[1], info.size[2] * 0.85);
      } else {
        coreGeo = new THREE.BoxGeometry(info.size[0] * 0.8, info.size[1], info.size[2] * 0.8);
      }

      const coreMat = new THREE.MeshStandardMaterial({
        color: '#1F2937',
        roughness: 0.4,
        metalness: 0.6,
        emissive: new THREE.Color(info.color),
        emissiveIntensity: 0.15
      });
      const coreMesh = new THREE.Mesh(coreGeo, coreMat);
      coreMesh.position.y = 0.3 + info.size[1] / 2;
      group.add(coreMesh);

      // Station Status Beacon / LED Crown
      const beaconGeo = new THREE.SphereGeometry(0.22, 16, 16);
      const beaconMat = new THREE.MeshBasicMaterial({ color: info.color });
      const beaconMesh = new THREE.Mesh(beaconGeo, beaconMat);
      beaconMesh.position.y = 0.4 + info.size[1] + 0.3;
      group.add(beaconMesh);

      // Text label sprite
      const canvasLabel = document.createElement('canvas');
      canvasLabel.width = 256;
      canvasLabel.height = 72;
      const ctx = canvasLabel.getContext('2d');
      if (ctx) {
        ctx.fillStyle = 'rgba(15, 23, 42, 0.85)';
        ctx.strokeStyle = info.color;
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.roundRect(4, 4, 248, 64, 8);
        ctx.fill();
        ctx.stroke();

        ctx.fillStyle = info.color;
        ctx.font = 'bold 24px monospace';
        ctx.textAlign = 'center';
        ctx.fillText(info.code, 128, 32);

        ctx.fillStyle = '#E2E8F0';
        ctx.font = 'bold 18px sans-serif';
        ctx.fillText(info.name.split(' ')[0], 128, 56);
      }
      const labelTexture = new THREE.CanvasTexture(canvasLabel);
      const labelMat = new THREE.SpriteMaterial({ map: labelTexture, transparent: true });
      const labelSprite = new THREE.Sprite(labelMat);
      labelSprite.position.set(0, 0.4 + info.size[1] + 1.2, 0);
      labelSprite.scale.set(3.2, 0.9, 1);
      group.add(labelSprite);

      // Tag for raycasting
      group.userData = { stationInfo: info };
      coreMesh.userData = { stationInfo: info };
      baseMesh.userData = { stationInfo: info };
      interactiveObjects.push(coreMesh, baseMesh);

      scene.add(group);
      stationMeshes.push({ mesh: group, info, coreMesh });
    });

    // 7. Build Connection Pipelines & Flowing Particles
    const connectionParticles: {
      points: THREE.Points;
      positions: Float32Array;
      curve: THREE.CatmullRomCurve3;
      speed: number;
      progress: Float32Array;
    }[] = [];

    FACTORY_CONNECTIONS.forEach((conn) => {
      // Create pipeline tube
      const p1 = new THREE.Vector3(...conn.fromPos);
      const p2 = new THREE.Vector3(...conn.toPos);
      // Slight elevation arc
      const mid = p1.clone().lerp(p2, 0.5).add(new THREE.Vector3(0, 0.4, 0));
      const curve = new THREE.CatmullRomCurve3([p1, mid, p2]);

      const tubeGeo = new THREE.TubeGeometry(curve, 32, 0.08, 8, false);
      const tubeMat = new THREE.MeshStandardMaterial({
        color: conn.pathType === 'batch' ? '#334155' : '#1E293B',
        roughness: 0.6,
        metalness: 0.5,
        transparent: true,
        opacity: 0.8
      });
      const tubeMesh = new THREE.Mesh(tubeGeo, tubeMat);
      scene.add(tubeMesh);

      // Animated glowing pulse particles along the pipe
      const particleCount = conn.pathType === 'batch' ? 8 : 16;
      const positions = new Float32Array(particleCount * 3);
      const progress = new Float32Array(particleCount);

      for (let i = 0; i < particleCount; i++) {
        progress[i] = i / particleCount;
        const pt = curve.getPoint(progress[i]);
        positions[i * 3] = pt.x;
        positions[i * 3 + 1] = pt.y;
        positions[i * 3 + 2] = pt.z;
      }

      const particleGeo = new THREE.BufferGeometry();
      particleGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3));

      const particleMat = new THREE.PointsMaterial({
        color: new THREE.Color(conn.color),
        size: 0.35,
        transparent: true,
        opacity: 0.9,
        blending: THREE.AdditiveBlending
      });

      const particlePoints = new THREE.Points(particleGeo, particleMat);
      scene.add(particlePoints);

      connectionParticles.push({
        points: particlePoints,
        positions,
        curve,
        speed: conn.pathType === 'batch' ? 0.08 : 0.22,
        progress
      });
    });

    // 8. Mouse & Interaction Controls
    const raycaster = new THREE.Raycaster();
    const mouse = new THREE.Vector2(-999, -999);
    let isDragging = false;
    let prevMouseX = 0;
    let prevMouseY = 0;
    let cameraAngle = Math.PI / 4;
    let cameraRadius = 45;
    let cameraPitch = 0.7; // radians above horizon
    let targetCameraLookAt = new THREE.Vector3(0, 0, 0);
    const currentCameraLookAt = new THREE.Vector3(0, 0, 0);

    const onPointerMove = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

      if (isDragging) {
        const deltaX = e.clientX - prevMouseX;
        const deltaY = e.clientY - prevMouseY;
        cameraAngle -= deltaX * 0.006;
        cameraPitch = Math.max(0.2, Math.min(Math.PI / 2.2, cameraPitch + deltaY * 0.005));
        prevMouseX = e.clientX;
        prevMouseY = e.clientY;
      }
    };

    const onPointerDown = (e: MouseEvent) => {
      isDragging = true;
      prevMouseX = e.clientX;
      prevMouseY = e.clientY;
    };

    const onPointerUp = () => {
      isDragging = false;
    };

    const onClick = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      const clickMouse = new THREE.Vector2(
        ((e.clientX - rect.left) / rect.width) * 2 - 1,
        -((e.clientY - rect.top) / rect.height) * 2 + 1
      );
      raycaster.setFromCamera(clickMouse, camera);
      const intersects = raycaster.intersectObjects(interactiveObjects, true);
      if (intersects.length > 0) {
        const hit = intersects[0];
        let station = hit.object.userData.stationInfo as StationInfo | undefined;
        if (!station && hit.object.parent) {
          station = hit.object.parent.userData.stationInfo as StationInfo | undefined;
        }
        if (station) {
          onSelectStationRef.current(station);
          targetCameraLookAt.set(station.position[0], station.position[1] + 1, station.position[2]);
        }
      }
    };

    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      cameraRadius = Math.max(18, Math.min(75, cameraRadius + e.deltaY * 0.04));
    };

    canvas.addEventListener('mousemove', onPointerMove);
    canvas.addEventListener('mousedown', onPointerDown);
    window.addEventListener('mouseup', onPointerUp);
    canvas.addEventListener('click', onClick);
    canvas.addEventListener('wheel', onWheel, { passive: false });

    // 9. Resize Handling
    const handleResize = () => {
      if (!container || !renderer) return;
      width = container.clientWidth || 800;
      height = container.clientHeight || 550;
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height);
    };

    const resizeObserver = new ResizeObserver(handleResize);
    resizeObserver.observe(container);

    // 10. Animation Loop
    let animationFrameId: number;
    let clock = new THREE.Clock();

    const animate = () => {
      animationFrameId = requestAnimationFrame(animate);
      const delta = Math.min(clock.getDelta(), 0.1);

      // Camera smooth follow
      currentCameraLookAt.lerp(targetCameraLookAt, 0.06);

      const cx = currentCameraLookAt.x + cameraRadius * Math.cos(cameraPitch) * Math.sin(cameraAngle);
      const cy = currentCameraLookAt.y + cameraRadius * Math.sin(cameraPitch);
      const cz = currentCameraLookAt.z + cameraRadius * Math.cos(cameraPitch) * Math.cos(cameraAngle);

      camera.position.set(cx, cy, cz);
      camera.lookAt(currentCameraLookAt);

      // Raycast for hover
      raycaster.setFromCamera(mouse, camera);
      const intersects = raycaster.intersectObjects(interactiveObjects, true);
      if (intersects.length > 0 && !isDragging) {
        let hoverStation = intersects[0].object.userData.stationInfo as StationInfo | undefined;
        if (!hoverStation && intersects[0].object.parent) {
          hoverStation = intersects[0].object.parent.userData.stationInfo as StationInfo | undefined;
        }
        if (hoverStation) {
          canvas.style.cursor = 'pointer';
          setHoveredStation(hoverStation);
        }
      } else {
        canvas.style.cursor = isDragging ? 'grabbing' : 'default';
        setHoveredStation(null);
      }

      // Station pulse & selection highlights
      stationMeshes.forEach(({ mesh, info, coreMesh }) => {
        const isSelected = info.id === selectedStationIdRef.current;
        const mat = coreMesh.material as THREE.MeshStandardMaterial;

        if (isSelected) {
          mat.emissiveIntensity = 0.5 + Math.sin(clock.getElapsedTime() * 5) * 0.2;
          mesh.scale.set(1.05, 1.05, 1.05);
        } else {
          mat.emissiveIntensity = 0.15;
          mesh.scale.set(1.0, 1.0, 1.0);
        }
      });

      // Flowing conveyor particles
      const isFlowing = wsConnectedRef.current && !reducedMotionRef.current;
      connectionParticles.forEach((cp) => {
        const posAttr = cp.points.geometry.attributes.position;
        const count = cp.progress.length;

        for (let i = 0; i < count; i++) {
          if (isFlowing) {
            cp.progress[i] = (cp.progress[i] + cp.speed * delta) % 1.0;
          }
          const pt = cp.curve.getPoint(cp.progress[i]);
          posAttr.setXYZ(i, pt.x, pt.y, pt.z);
        }
        posAttr.needsUpdate = true;
      });

      renderer.render(scene, camera);
    };

    animate();

    // 11. Cleanup
    return () => {
      cancelAnimationFrame(animationFrameId);
      resizeObserver.disconnect();
      canvas.removeEventListener('mousemove', onPointerMove);
      canvas.removeEventListener('mousedown', onPointerDown);
      window.removeEventListener('mouseup', onPointerUp);
      canvas.removeEventListener('click', onClick);
      canvas.removeEventListener('wheel', onWheel);

      scene.traverse((obj) => {
        if (obj instanceof THREE.Mesh) {
          obj.geometry?.dispose();
          if (Array.isArray(obj.material)) {
            obj.material.forEach((m) => m.dispose());
          } else if (obj.material) {
            obj.material.dispose();
          }
        }
      });

      renderer.dispose();
    };
  }, []);

  return (
    <div
      ref={containerRef}
      style={{
        width: '100%',
        height: '100%',
        position: 'relative',
        overflow: 'hidden',
        background: '#0B0E11'
      }}
    >
      <canvas
        ref={canvasRef}
        style={{
          width: '100%',
          height: '100%',
          display: 'block',
          outline: 'none'
        }}
      />

      {/* Floating Hover Card */}
      {hoveredStation && (
        <div
          style={{
            position: 'absolute',
            bottom: '16px',
            left: '16px',
            background: 'rgba(18, 22, 26, 0.92)',
            border: `1px solid ${hoveredStation.color}`,
            borderRadius: '6px',
            padding: '10px 14px',
            pointerEvents: 'none',
            boxShadow: '0 8px 24px rgba(0, 0, 0, 0.6)',
            maxWidth: '300px'
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
            <span
              style={{
                fontFamily: 'monospace',
                fontSize: '11px',
                padding: '2px 6px',
                borderRadius: '3px',
                background: hoveredStation.color,
                color: '#0B0E11',
                fontWeight: 700
              }}
            >
              {hoveredStation.code}
            </span>
            <span style={{ fontSize: '13px', fontWeight: 600, color: '#EAECEF' }}>
              {hoveredStation.name}
            </span>
          </div>
          <div style={{ fontSize: '11px', color: '#848E9C' }}>
            {hoveredStation.subtitle}
          </div>
          <div style={{ fontSize: '10px', color: hoveredStation.color, marginTop: '6px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            Click to inspect telemetry
          </div>
        </div>
      )}

      {/* 3D Navigation Controls Hint */}
      <div
        style={{
          position: 'absolute',
          top: '12px',
          right: '12px',
          background: 'rgba(18, 22, 26, 0.75)',
          border: '1px solid #222B35',
          borderRadius: '4px',
          padding: '6px 10px',
          fontSize: '11px',
          color: '#848E9C',
          display: 'flex',
          gap: '12px',
          pointerEvents: 'none'
        }}
      >
        <span>Drag to rotate</span>
        <span>•</span>
        <span>Scroll to zoom</span>
        <span>•</span>
        <span>Click node to inspect</span>
      </div>
    </div>
  );
};
