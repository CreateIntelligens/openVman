/** Generic surface/texture compositor. Character-specific rig decoding lives in character-adapter.mjs. */
const QUAD = `#version 300 es
precision highp float;
out vec2 uv;
void main(){vec2 p=vec2((gl_VertexID<<1)&2,gl_VertexID&2);uv=p;gl_Position=vec4(p*2.-1.,0.,1.);}`;
const SURFACE_VERTEX = `#version 300 es
precision highp float;
layout(location=0) in vec3 point;
layout(location=1) in vec3 normal;
layout(location=2) in vec2 atlasUv;
layout(location=3) in vec2 displacement;
layout(location=4) in float material;
uniform vec2 size;
out vec3 surfacePoint;out vec3 surfaceNormal;out vec2 texturePoint;out vec2 flow;flat out int surfaceMaterial;
void main(){gl_Position=vec4(point.xy/size*2.-1.,point.z*.001,1.);surfacePoint=point;surfaceNormal=normal;texturePoint=atlasUv;flow=displacement;surfaceMaterial=int(material);}`;
const SURFACE_FRAGMENT = `#version 300 es
precision highp float;
in vec3 surfacePoint;in vec3 surfaceNormal;in vec2 texturePoint;in vec2 flow;flat in int surfaceMaterial;
uniform sampler2D atlas;
layout(location=0) out vec4 coordinateField;
layout(location=1) out vec4 colorField;
layout(location=2) out vec4 positionField;
layout(location=3) out vec4 normalField;
void main(){
 vec4 paint=texture(atlas,texturePoint);
 float coverage=surfaceMaterial==1?1.:0.;
 if(coverage>0. && all(greaterThan(paint.rgb,vec3(.999))))coverage=0.;
 coordinateField=vec4(surfaceMaterial==0?flow:vec2(0.),0.,1.);
 colorField=vec4(paint.rgb,coverage);
 positionField=vec4(surfacePoint,1.);normalField=vec4(normalize(surfaceNormal),1.);
}`;
const COMPOSE = `#version 300 es
precision highp float;
in vec2 uv;out vec4 color;
uniform sampler2D coordinateField;uniform sampler2D colorField;uniform sampler2D positionField;uniform sampler2D normalField;uniform sampler2D skin;uniform sampler2D influence;
uniform vec2 size;
void main(){
 vec2 d=texture(coordinateField,uv).xy;
 vec2 sampleAt=clamp(uv-d*texture(influence,uv).r,vec2(.5)/size,1.-vec2(.5)/size);
 vec3 face=texture(skin,sampleAt).rgb;
 vec4 paint=texture(colorField,uv);
 if(paint.a>.5){
  vec3 n=normalize(texture(normalField,uv).xyz),p=texture(positionField,uv).xyz;
  vec3 helper=abs(n.z)<.95?vec3(0.,0.,1.):vec3(1.,0.,0.);
  vec3 tangent=normalize(cross(helper,n)),bitangent=cross(n,tangent);
  float visible=0.;
  for(int i=0;i<32;i++){
   float u=(float(i)+.5)/32.,angle=float(i)*2.39996323;
   float radial=sqrt(u),height=sqrt(1.-u);
   vec3 direction=tangent*(cos(angle)*radial)+bitangent*(sin(angle)*radial)+n*height;
   vec3 probe=p+direction*(size.x/6.);
   vec2 hit=probe.xy/size;
   float depth=texture(positionField,hit).z;
   visible+=depth>probe.z-.025?1.:0.;
  }
  float brightness=(.7+.3*max(0.,-n.z))*(visible/32.);
  face=paint.rgb*brightness;
 }
 color=vec4(face,1.);
}`;
// Generic align-corners rectangle resampler; the character profile supplies bounds and dimensions.
const RESAMPLE = `#version 300 es
precision highp float;
out vec4 color;uniform sampler2D source;uniform vec2 inputSize;uniform vec2 outputSize;uniform vec4 rect;
void main(){vec2 p=(gl_FragCoord.xy-.5)/max(outputSize-1.,vec2(1.));vec2 q=rect.xy+p*(rect.zw-1.);color=texture(source,(q+.5)/inputSize);}`;
const INSERT = `#version 300 es
precision highp float;
out vec4 color;uniform sampler2D fullImage;uniform sampler2D detail;uniform vec2 imageSize;uniform vec2 detailSize;uniform vec4 rect;
void main(){vec2 pixel=gl_FragCoord.xy-.5;if(all(greaterThanEqual(pixel,rect.xy))&&all(lessThan(pixel,rect.xy+rect.zw))){vec2 fraction=(pixel-rect.xy)/(rect.zw-1.);color=texture(detail,(fraction*(detailSize-1.)+.5)/detailSize);}else color=texelFetch(fullImage,ivec2(pixel),0);}`;
export class SurfaceRenderer {
  constructor(canvas, asset) {
    this.canvas = canvas;
    this.asset = asset;
    this.gl = canvas.getContext("webgl2", {
      alpha: true,
      antialias: false,
      preserveDrawingBuffer: true,
    });
    const g = this.gl;
    if (!g || !g.getExtension("EXT_color_buffer_float"))
      throw new Error("Float render targets required");
    this.resources = {
      programs: [],
      textures: [],
      framebuffers: [],
      buffers: [],
      renderbuffers: [],
    };
    this.surface = this.program(SURFACE_VERTEX, SURFACE_FRAGMENT);
    this.compose = this.program(QUAD, COMPOSE);
    this.resample = this.program(QUAD, RESAMPLE);
    this.insert = this.program(QUAD, INSERT);
    this.vao = g.createVertexArray();
    g.bindVertexArray(this.vao);
    this.vertices = g.createBuffer();
    this.resources.buffers.push(this.vertices);
    g.bindBuffer(g.ARRAY_BUFFER, this.vertices);
    g.bufferData(g.ARRAY_BUFFER, asset.count * 48, g.DYNAMIC_DRAW);
    const layout = [
      [3, 0],
      [3, 12],
      [2, 24],
      [2, 32],
      [1, 40],
    ];
    layout.forEach(([n, o], i) => {
      g.enableVertexAttribArray(i);
      g.vertexAttribPointer(i, n, g.FLOAT, false, 48, o);
    });
    this.indices = g.createBuffer();
    this.resources.buffers.push(this.indices);
    g.bindBuffer(g.ELEMENT_ARRAY_BUFFER, this.indices);
    g.bufferData(g.ELEMENT_ARRAY_BUFFER, asset.indices, g.STATIC_DRAW);
    this.quad = g.createVertexArray();
    this.surfaceTarget = this.target(180, 180, 4, true, true);
    this.blended = this.target(180, 180);
    this.small = this.target(64, 48);
    this.final = this.target(180, 180);
    this.skin = this.texture(180, 180, null);
    this.atlas = this.texture(576, 192, asset.teeth);
    this.influence = this.texture(180, 180, asset.weights);
  }
  program(vs, fs) {
    const g = this.gl;
    const p = g.createProgram();
    for (const [kind, code] of [
      [g.VERTEX_SHADER, vs],
      [g.FRAGMENT_SHADER, fs],
    ]) {
      const s = g.createShader(kind);
      g.shaderSource(s, code);
      g.compileShader(s);
      if (!g.getShaderParameter(s, g.COMPILE_STATUS))
        throw new Error(g.getShaderInfoLog(s));
      g.attachShader(p, s);
      g.deleteShader(s);
    }
    g.linkProgram(p);
    if (!g.getProgramParameter(p, g.LINK_STATUS))
      throw new Error(g.getProgramInfoLog(p));
    this.resources.programs.push(p);
    return p;
  }
  texture(w, h, data, float = false) {
    const g = this.gl,
      t = g.createTexture();
    this.resources.textures.push(t);
    g.bindTexture(g.TEXTURE_2D, t);
    g.texParameteri(
      g.TEXTURE_2D,
      g.TEXTURE_MIN_FILTER,
      float ? g.NEAREST : g.LINEAR,
    );
    g.texParameteri(
      g.TEXTURE_2D,
      g.TEXTURE_MAG_FILTER,
      float ? g.NEAREST : g.LINEAR,
    );
    g.texParameteri(g.TEXTURE_2D, g.TEXTURE_WRAP_S, g.CLAMP_TO_EDGE);
    g.texParameteri(g.TEXTURE_2D, g.TEXTURE_WRAP_T, g.CLAMP_TO_EDGE);
    g.texImage2D(
      g.TEXTURE_2D,
      0,
      float ? g.RGBA32F : g.RGBA,
      w,
      h,
      0,
      g.RGBA,
      float ? g.FLOAT : g.UNSIGNED_BYTE,
      data,
    );
    return t;
  }
  target(w, h, count = 1, float = false, depth = false) {
    const g = this.gl,
      f = g.createFramebuffer();
    this.resources.framebuffers.push(f);
    g.bindFramebuffer(g.FRAMEBUFFER, f);
    const colors = [];
    for (let i = 0; i < count; i++) {
      const t = this.texture(w, h, null, float);
      colors.push(t);
      g.framebufferTexture2D(
        g.FRAMEBUFFER,
        g.COLOR_ATTACHMENT0 + i,
        g.TEXTURE_2D,
        t,
        0,
      );
    }
    g.drawBuffers(colors.map((_, i) => g.COLOR_ATTACHMENT0 + i));
    if (depth) {
      const d = g.createRenderbuffer();
      this.resources.renderbuffers.push(d);
      g.bindRenderbuffer(g.RENDERBUFFER, d);
      g.renderbufferStorage(g.RENDERBUFFER, g.DEPTH_COMPONENT24, w, h);
      g.framebufferRenderbuffer(
        g.FRAMEBUFFER,
        g.DEPTH_ATTACHMENT,
        g.RENDERBUFFER,
        d,
      );
    }
    if (g.checkFramebufferStatus(g.FRAMEBUFFER) !== g.FRAMEBUFFER_COMPLETE)
      throw new Error("Incomplete framebuffer");
    return { f, colors, w, h };
  }
  bind(program, target) {
    const g = this.gl;
    g.useProgram(program);
    g.bindFramebuffer(g.FRAMEBUFFER, target.f);
    g.viewport(0, 0, target.w, target.h);
    g.bindVertexArray(this.quad);
  }
  vector(p, name, ...v) {
    const g = this.gl,
      loc = g.getUniformLocation(p, name);
    if (v.length === 2) g.uniform2f(loc, ...v);
    else g.uniform4f(loc, ...v);
  }
  sampler(p, name, t, unit) {
    const g = this.gl;
    g.activeTexture(g.TEXTURE0 + unit);
    g.bindTexture(g.TEXTURE_2D, t);
    g.uniform1i(g.getUniformLocation(p, name), unit);
  }
  render(geometry, skin) {
    const g = this.gl;
    g.pixelStorei(g.UNPACK_FLIP_Y_WEBGL, false);
    g.activeTexture(g.TEXTURE0);
    g.bindTexture(g.TEXTURE_2D, this.skin);
    g.texImage2D(g.TEXTURE_2D, 0, g.RGBA, g.RGBA, g.UNSIGNED_BYTE, skin);
    this.bind(this.surface, this.surfaceTarget);
    g.bindVertexArray(this.vao);
    g.bindBuffer(g.ARRAY_BUFFER, this.vertices);
    g.bufferSubData(g.ARRAY_BUFFER, 0, geometry);
    g.enable(g.DEPTH_TEST);
    g.depthFunc(g.LESS);
    g.clearColor(0, 0, 0, 0);
    g.clear(g.COLOR_BUFFER_BIT | g.DEPTH_BUFFER_BIT);
    this.vector(this.surface, "size", 180, 180);
    this.sampler(this.surface, "atlas", this.atlas, 0);
    g.drawElements(g.TRIANGLES, this.asset.indices.length, g.UNSIGNED_INT, 0);
    g.disable(g.DEPTH_TEST);
    this.bind(this.compose, this.blended);
    ["coordinateField", "colorField", "positionField", "normalField"].forEach(
      (name, i) =>
        this.sampler(this.compose, name, this.surfaceTarget.colors[i], i),
    );
    this.sampler(this.compose, "skin", this.skin, 4);
    this.sampler(this.compose, "influence", this.influence, 5);
    this.vector(this.compose, "size", 180, 180);
    g.drawArrays(g.TRIANGLES, 0, 3);
    this.bind(this.resample, this.small);
    this.sampler(this.resample, "source", this.blended.colors[0], 0);
    this.vector(this.resample, "inputSize", 180, 180);
    this.vector(this.resample, "outputSize", 64, 48);
    this.vector(this.resample, "rect", 42, 54, 96, 72);
    g.drawArrays(g.TRIANGLES, 0, 3);
    this.bind(this.insert, this.final);
    this.sampler(this.insert, "fullImage", this.blended.colors[0], 0);
    this.sampler(this.insert, "detail", this.small.colors[0], 1);
    this.vector(this.insert, "imageSize", 180, 180);
    this.vector(this.insert, "detailSize", 64, 48);
    this.vector(this.insert, "rect", 42, 54, 96, 72);
    g.drawArrays(g.TRIANGLES, 0, 3);
    g.bindFramebuffer(g.READ_FRAMEBUFFER, this.final.f);
    g.bindFramebuffer(g.DRAW_FRAMEBUFFER, null);
    g.blitFramebuffer(
      0,
      0,
      180,
      180,
      0,
      180,
      180,
      0,
      g.COLOR_BUFFER_BIT,
      g.NEAREST,
    );
  }
  dispose() {
    const g = this.gl;
    for (const [kind, items] of Object.entries(this.resources)) {
      const method = {
        programs: "deleteProgram",
        textures: "deleteTexture",
        framebuffers: "deleteFramebuffer",
        buffers: "deleteBuffer",
        renderbuffers: "deleteRenderbuffer",
      }[kind];
      for (const item of items) g[method](item);
    }
    g.deleteVertexArray(this.vao);
    g.deleteVertexArray(this.quad);
  }
}
