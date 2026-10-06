// qrcode-terminal ships no types, and this is the only call made to it.
declare module "qrcode-terminal" {
  const qrcode: {
    generate(text: string, options: { small: boolean }, callback: (qr: string) => void): void;
  };
  export default qrcode;
}
