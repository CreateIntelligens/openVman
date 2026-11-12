/**
 * Project-authored video-texture compositor. A generated annular mesh carries
 * the source lips and surrounding skin; a separately shaded mouth interior is
 * visible only inside that mesh's inner boundary. No inherited GLSL or atlas.
 */
const VERTEX = `#version 300 es
precision highp float;
layout(location=0) in vec2 point;
layout(location=1) in vec2 source;
layout(location=2) in float material;
layout(location=3) in vec2 rest;
out vec2 uv;out float dentalCoverage;out vec2 restUv;flat out int surface;
void main(){gl_Position=vec4(point.x/90.-1.,1.-point.y/90.,0.,1.);uv=source;dentalCoverage=max(0.,material-1.);restUv=rest;surface=int(material);}`;
// The interior is lit and tinted by sampling this person's own frame, so teeth and
// gums sit in the video's lighting. It stays a soft dark red, never black: at the rim
// it starts from the lip's own shade, so a narrow opening reads as a dim slit rather
// than an inked line. Teeth recede towards the corners and under the upper lip.
const FRAGMENT = `#version 300 es
precision highp float;
in vec2 uv;in float dentalCoverage;in vec2 restUv;flat in int surface;out vec4 color;
uniform sampler2D skin;uniform sampler2D dental;uniform float exposure;uniform float opening;uniform float reach;uniform float tilt;
uniform vec4 teeth;uniform vec2 lipProbe;uniform vec4 cheekProbes;
vec3 oral(vec2 p){
  float side=abs(p.x);
  vec4 crown=texture(dental,vec2(p.x*.5+.5,.5));
  vec3 lip=texture(skin,lipProbe).rgb;
  vec3 cheekA=texture(skin,cheekProbes.xy).rgb,cheekB=texture(skin,cheekProbes.zw).rgb;
  vec3 toLuma=vec3(.3,.59,.11);
  // The brightest of lip and both cheeks: any single spot may sit under a beard or shadow.
  float cheekLuma=max(dot(cheekA,toLuma),dot(cheekB,toLuma));
  float light=clamp(max(dot(lip,toLuma)*1.25,cheekLuma),.42,1.);
  vec3 skinTint=(dot(cheekA,toLuma)>dot(cheekB,toLuma)?cheekA:cheekB)/max(cheekLuma,.2);
  float depth=1.-smoothstep(.36,.98,side);
  vec3 back=lip*vec3(.4,.18,.19)*(.5+.5*depth)*(.62+.5*smoothstep(-.04,.16,p.y)*(1.-side*side));
  float seam=teeth.z*p.x*p.x+tilt*p.x;
  float lowerEdge=teeth.y+seam*.9+.022*side*side+(1.-crown.a)*.012;
  // The tongue rests behind the lower teeth and fills the floor of the mouth as the
  // rows part, lower towards the corners.
  float tongueTop=lowerEdge-.012-.35*max(0.,lowerEdge-teeth.x)+.05*side*side;
  float tongue=smoothstep(tongueTop-.02,tongueTop+.03,p.y)*(1.-side*side);
  vec3 col=mix(back,lip*vec3(.64,.38,.38)*(.55+.45*depth),tongue*.85);
  vec3 enamel=vec3(.97,.94,.88)*mix(vec3(1.),skinTint,.25)*light;
  // Crowns separate at the biting edge and merge towards the gum, so grooves fade
  // away from it instead of ruling a straight line through every tooth.
  float lowerEdgeNear=1.-smoothstep(lowerEdge+.006,lowerEdge+.05,p.y);
  float lowerBody=mix(1.,crown.b,.3+.7*lowerEdgeNear);
  // A slit between nearly closed lips is too thin to show separate teeth.
  float showTeeth=smoothstep(.025,.075,opening);
  float lowerTeeth=showTeeth*smoothstep(lowerEdge-.009,lowerEdge+.009,p.y)*(1.-smoothstep(.62,.95,side));
  // Shaded enamel falls towards the person's warm oral tone, not towards grey.
  vec3 shaded=lip*vec3(.36,.24,.24);
  col=mix(col,mix(shaded,enamel*lowerBody*mix(1.,.92,lowerEdgeNear),.3+.66*depth),lowerTeeth*.95);
  float upperEdge=teeth.x+seam-.02*side*side-(1.-crown.g)*.01;
  // Upper teeth overlap the lower row and shade it, which keeps closed rows legible.
  col*=1.-.4*(1.-smoothstep(0.,.024,p.y-upperEdge));
  float upperEdgeNear=smoothstep(upperEdge-.05,upperEdge-.006,p.y);
  float upperBody=mix(1.,crown.r,.3+.7*upperEdgeNear);
  float upperTeeth=showTeeth*(1.-smoothstep(upperEdge-.009,upperEdge+.009,p.y))*(1.-smoothstep(.54,.9,side));
  float shadow=mix(.45,1.,smoothstep(0.,.07,p.y-(teeth.w+seam)));
  float upperDepth=1.-smoothstep(.14,.84,side);
  col=mix(col,mix(shaded,enamel*upperBody,(.26+.62*upperDepth)*shadow),upperTeeth*.9);
  float rim=smoothstep(0.,.14,dentalCoverage)*mix(.3,1.,smoothstep(.015,.09,opening));
  return mix(lip*vec3(.46,.28,.29),col,rim);
}
void main(){
  vec4 mapped;
  if(surface==0){
    // MSAA can evaluate just outside a triangle, so this ramp must tolerate overshoot.
    float wet=clamp(restUv.x,0.,1.);
    mapped=texture(skin,uv);mapped.rgb*=1.-.14*exposure*wet*wet;
    // The lip rolls into the mouth rather than ending at a cut edge; the last sliver
    // falls towards the interior so the opening is as soft as the face around it.
    float rolled=smoothstep(.55,1.,wet)*exposure;
    mapped.rgb=mix(mapped.rgb,texture(skin,lipProbe).rgb*vec3(.46,.28,.29),rolled*.72);
    mapped.a*=clamp(restUv.y,0.,1.);
  }else{
    vec4 seam=texture(skin,restUv);
    // Past the unzipped part the lips still touch, so the video's own seam stays: the
    // opening grows out from the middle instead of appearing as a full-width line.
    float parted=1.-smoothstep(reach-.14,reach+.04,abs(uv.x));
    mapped=vec4(mix(seam.rgb,oral(uv),exposure*parted*smoothstep(0.,.14,dentalCoverage)),max(seam.a,exposure));
  }
  color=mapped;
}`;
export class SurfaceRenderer {
  constructor(canvas, asset) {
    this.canvas = canvas;
    this.asset = asset;
    const g = this.gl = canvas.getContext('webgl2', {
      alpha: true, premultipliedAlpha: false, antialias: true,
      preserveDrawingBuffer: true,
    });
    if (!g) throw new Error('WebGL 2 required');
    this.textures = new Set();
    this.pendingShaders = new Set();
    this.disposed = false;
    try {
      this.program = g.createProgram();
      if (!this.program) throw new Error('Unable to allocate renderer program');
      for (const [kind, code] of [[g.VERTEX_SHADER, VERTEX], [g.FRAGMENT_SHADER, FRAGMENT]]) {
        const shader = g.createShader(kind);
        if (!shader) throw new Error('Unable to allocate renderer shader');
        this.pendingShaders.add(shader);
        g.shaderSource(shader, code); g.compileShader(shader);
        if (!g.getShaderParameter(shader, g.COMPILE_STATUS)) throw new Error(g.getShaderInfoLog(shader));
        g.attachShader(this.program, shader); g.deleteShader(shader);
        this.pendingShaders.delete(shader);
      }
      g.linkProgram(this.program);
      if (!g.getProgramParameter(this.program, g.LINK_STATUS)) throw new Error(g.getProgramInfoLog(this.program));
      this.vao = g.createVertexArray();
      if (!this.vao) throw new Error('Unable to allocate renderer vertex array');
      g.bindVertexArray(this.vao);
      this.buffer = g.createBuffer();
      if (!this.buffer) throw new Error('Unable to allocate renderer vertex buffer');
      g.bindBuffer(g.ARRAY_BUFFER, this.buffer);
      for (const [index, count, offset] of [[0, 2, 0], [1, 2, 8], [2, 1, 16], [3, 2, 20]]) {
        g.enableVertexAttribArray(index); g.vertexAttribPointer(index, count, g.FLOAT, false, 28, offset);
      }
      this.indices = g.createBuffer();
      if (!this.indices) throw new Error('Unable to allocate renderer index buffer');
      g.bindBuffer(g.ELEMENT_ARRAY_BUFFER, this.indices);
      g.bufferData(g.ELEMENT_ARRAY_BUFFER, asset.indices, g.STATIC_DRAW);
      this.skin = this.texture(180, 180, null);
      this.dental = this.texture(...asset.atlasSize, asset.teeth);
      this.locations = Object.fromEntries(
        ['skin', 'dental', 'exposure', 'opening', 'reach', 'tilt', 'teeth', 'lipProbe', 'cheekProbes']
          .map(name => [name, g.getUniformLocation?.(this.program, name)]),
      );
    } catch (error) {
      // The caller cannot dispose a constructor that never returned.
      this.dispose();
      throw error;
    }
  }

  texture(width, height, data) {
    const g = this.gl, texture = g.createTexture();
    if (!texture) throw new Error('Unable to allocate renderer texture');
    this.textures.add(texture); g.bindTexture(g.TEXTURE_2D, texture);
    g.texParameteri(g.TEXTURE_2D, g.TEXTURE_MIN_FILTER, g.LINEAR);
    g.texParameteri(g.TEXTURE_2D, g.TEXTURE_MAG_FILTER, g.LINEAR);
    g.texParameteri(g.TEXTURE_2D, g.TEXTURE_WRAP_S, g.CLAMP_TO_EDGE);
    g.texParameteri(g.TEXTURE_2D, g.TEXTURE_WRAP_T, g.CLAMP_TO_EDGE);
    g.texImage2D(g.TEXTURE_2D, 0, g.RGBA, width, height, 0, g.RGBA, g.UNSIGNED_BYTE, data);
    return texture;
  }

  render(geometry, skin) {
    const g = this.gl;
    g.viewport(0, 0, this.canvas.width, this.canvas.height); g.useProgram(this.program); g.bindVertexArray(this.vao);
    g.disable(g.DEPTH_TEST); g.disable(g.BLEND); g.disable(g.CULL_FACE);
    g.pixelStorei(g.UNPACK_FLIP_Y_WEBGL, false);
    g.activeTexture(g.TEXTURE0); g.bindTexture(g.TEXTURE_2D, this.skin);
    g.texImage2D(g.TEXTURE_2D, 0, g.RGBA, g.RGBA, g.UNSIGNED_BYTE, skin);
    const at = this.locations;
    g.uniform1i(at.skin, 0);
    g.activeTexture(g.TEXTURE1); g.bindTexture(g.TEXTURE_2D, this.dental);
    g.uniform1i(at.dental, 1);
    g.uniform1f(at.exposure, geometry.exposure);
    const { dental } = geometry;
    g.uniform1f(at.opening, dental.opening);
    g.uniform1f(at.reach, dental.reach);
    g.uniform1f(at.tilt, dental.tilt);
    g.uniform4f(at.teeth, dental.upperEdge, dental.lowerEdge, dental.bend, dental.upperLip);
    g.uniform2f(at.lipProbe, dental.lipProbe[0], dental.lipProbe[1]);
    g.uniform4f(at.cheekProbes, dental.cheekProbes[0], dental.cheekProbes[1],
      dental.cheekProbes[2], dental.cheekProbes[3]);
    g.bindBuffer(g.ARRAY_BUFFER, this.buffer);
    // Anything left transparent keeps the untouched video pixels underneath.
    g.clearColor(0, 0, 0, 0); g.clear(g.COLOR_BUFFER_BIT);
    if (!geometry.neutral) {
      g.bufferData(g.ARRAY_BUFFER, geometry.cavity, g.DYNAMIC_DRAW);
      g.drawArrays(g.TRIANGLE_FAN, 0, geometry.cavity.length / 7);
      g.bufferData(g.ARRAY_BUFFER, geometry.skin, g.DYNAMIC_DRAW);
      g.drawElements(g.TRIANGLES, this.asset.indices.length, g.UNSIGNED_INT, 0);
    }
    // Without this, the 2D copy of this canvas intermittently returns an older
    // snapshot, which shows up as a previous mouth shape flashing back for a paint.
    g.flush();
  }

  dispose() {
    if (this.disposed) return;
    this.disposed = true;
    const g = this.gl;
    for (const shader of this.pendingShaders) g.deleteShader(shader);
    this.pendingShaders.clear();
    for (const texture of this.textures) g.deleteTexture(texture);
    this.textures.clear();
    if (this.buffer) g.deleteBuffer(this.buffer);
    if (this.indices) g.deleteBuffer(this.indices);
    if (this.vao) g.deleteVertexArray(this.vao);
    if (this.program) g.deleteProgram(this.program);
    g.getExtension('WEBGL_lose_context')?.loseContext();
  }
}
